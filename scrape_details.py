#!/usr/bin/env python3
"""
Step 2: Detail scrape — open each map, extract description, share/embed URLs,
and optionally take map + elevation screenshots.

Reads folders.json and processes only include=Y items.
Merges results into mapy_data.json.
Resets processed include flags to N after each completed folder.

  Folder include=Y  →  scrape all maps in the folder (ignores map-level include)
  Folder include=N  →  scrape only maps where map include=Y

Run scrape_folders.py first, optionally edit folders.json, then run this.
"""
import asyncio
import json
import os
import re
import shutil
import sqlite3
from collections import deque
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, Page

FIREFOX_PROFILE = Path(
    r"C:\Users\roman\AppData\Roaming\Mozilla\Firefox\Profiles"
    r"\3yclgs3h.dev-edition-default"
)
MAPY_URL = "https://mapy.com/en/turisticka?moje-mapy&cat=mista-trasy"
FOLDERS_FILE = Path(__file__).parent / "folders.json"
DATA_FILE = Path(__file__).parent / "mapy_data.json"
IMAGES_DIR = Path(__file__).parent / "images"
HEADLESS = False
TAKE_SCREENSHOTS = True
FOLDER_SCREENSHOT_EXTRA_WAIT = 7000  # ms extra wait before folder screenshot (increase if routes missing)


async def detect_type_from_item(page, mi: int) -> str:
    """Detect route type from the mapy-icon shadow DOM SVG path fingerprint.
    Uses page.evaluate() with the list index to avoid locator-resolution timeouts."""
    return await page.evaluate(f"""() => {{
        const item = document.querySelectorAll('ul.items.sortable li.item')[{mi}];
        if (!item) return '';
        const cover = item.querySelector('div.image-cover');
        if (cover) {{
            const cls = (cover.className || '').split(' ');
            if (cls.includes('icon') && !cls.includes('svg')) return 'adr';
        }}
        const icon = item.querySelector('div.image-cover.svg mapy-icon');
        if (!icon || !icon.shadowRoot) return '';
        const path = icon.shadowRoot.querySelector('path');
        const d = path ? (path.getAttribute('d') || '') : '';
        if (d.startsWith('M3.75 16.5C2.7125')) return 'bike';
        if (d.startsWith('M2.98168')) return 'car';
        if (d.startsWith('M6.95625 16.65')) return 'hiking';
        return '';
    }}""")


def read_firefox_cookies(profile_dir: Path, domain: str = "mapy.com") -> list[dict]:
    db = profile_dir / "cookies.sqlite"
    tmp_fd, tmp = tempfile.mkstemp(suffix=".sqlite")
    os.close(tmp_fd)
    shutil.copy2(db, tmp)
    try:
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT name, value, host, path, expiry, isSecure, isHttpOnly, sameSite "
            "FROM moz_cookies WHERE host LIKE ?", (f"%{domain}%",)
        ).fetchall()
        conn.close()
    finally:
        os.unlink(tmp)
    sm = {0: "None", 1: "Lax", 2: "Strict"}
    return [{
        "name": r["name"], "value": r["value"], "domain": r["host"], "path": r["path"],
        "expires": int(r["expiry"] / 1000) if r["expiry"] > 1e10 else (r["expiry"] if r["expiry"] > 0 else -1),
        "secure": bool(r["isSecure"]), "httpOnly": bool(r["isHttpOnly"]),
        "sameSite": sm.get(r["sameSite"], "None"),
    } for r in rows]


async def get_share_urls(page: Page) -> tuple[str, str]:
    """Click Share, enable public toggle, extract share URL and embed src."""
    share_btn = page.locator("button").filter(has_text="dílet").first
    if not await share_btn.count():
        return "", ""

    try:
        await share_btn.click(timeout=5000)
        await page.wait_for_timeout(1200)
    except Exception:
        return "", ""

    # Enable "Sdílet s ostatními" (public sharing) toggle if off
    toggle = page.locator("label.switch input[type='checkbox']").first
    if await toggle.count():
        try:
            if not await toggle.is_checked():
                await toggle.check()
                await page.wait_for_timeout(600)
        except Exception:
            pass

    # Extract share URL via JS (input.value is a DOM property, not HTML attribute)
    share_link = await page.evaluate("""() => {
        for (const inp of document.querySelectorAll('input')) {
            if (inp.value && inp.value.includes('mapy.com/s/')) return inp.value;
        }
        return '';
    }""")

    # Try embed tab ("Vložit mapu do vlastních stránek")
    embed_src = ""
    embed_tab = page.locator("span.share-switch").filter(has_text="lo").first  # "Vložit"
    if await embed_tab.count():
        try:
            await embed_tab.click(timeout=2000)
            await page.wait_for_timeout(800)
            embed_src = await page.evaluate("""() => {
                for (const el of document.querySelectorAll('input, textarea')) {
                    const v = el.value || '';
                    const m = v.match(/src="(https:\\/\\/mapy\\.com\\/s\\/[^"]+)"/);
                    if (m) return m[1];
                    if (v.includes('mapy.com/s/')) return v;
                }
                return '';
            }""")
        except Exception:
            pass

    # Close dialog
    try:
        close_btn = page.locator("button.close").first
        if await close_btn.count():
            await close_btn.click(timeout=1000)
        else:
            await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
    except Exception:
        pass

    if share_link and not embed_src:
        embed_src = share_link

    return share_link, embed_src


async def take_map_screenshot(page: Page, code: str) -> str:
    """Screenshot div#map.smap (map canvas only). Returns relative path or ''."""
    IMAGES_DIR.mkdir(exist_ok=True)
    await page.wait_for_timeout(2500)  # wait for tiles to render
    for sel in ("div#map.smap", "div.smap", "#map"):
        el = page.locator(sel).first
        try:
            if await el.count() and await el.is_visible():
                path = IMAGES_DIR / f"{code}.png"
                await el.screenshot(path=str(path))
                return f"images/{code}.png"
        except Exception:
            continue
    return ""


async def take_elevation_screenshot(page: Page, code: str) -> str:
    """Click elevation header to expand it, then screenshot the chart."""
    IMAGES_DIR.mkdir(exist_ok=True)
    header = page.locator("div.route-height-profile-form-header").first
    if not await header.count():
        return ""
    try:
        await header.click(timeout=3000)
        await page.wait_for_timeout(900)
    except Exception:
        return ""
    for sel in ("div.module-content div.line-chart", "div.line-chart"):
        el = page.locator(sel).first
        try:
            if await el.count() and await el.is_visible():
                path = IMAGES_DIR / f"{code}_elev.png"
                await el.screenshot(path=str(path))
                return f"images/{code}_elev.png"
        except Exception:
            continue
    return ""


async def get_folder_share_url(page: Page, fi: int) -> str:
    """Click span.opts on folder, look for share option, extract URL."""
    try:
        folder_el = page.locator("li.folder").nth(fi)
        opts = folder_el.locator("span.opts").first
        if not await opts.count():
            print(f"    [share] no opts button for folder {fi}")
            return ""
        await folder_el.hover()
        await page.wait_for_timeout(500)
        try:
            await opts.click(timeout=3000)
        except Exception:
            await opts.click(timeout=3000, force=True)
        await page.wait_for_timeout(700)
        # English UI: "Share" / Czech UI: "sdílet" — match both
        share_btn = page.locator("div.ui-contextmenu button.ui-contextmenuitem").filter(
            has_text=re.compile(r"share|d[ií]let", re.IGNORECASE)
        ).first
        if not await share_btn.count():
            print(f"    [share] no share button in context menu for folder {fi}")
            await page.keyboard.press("Escape")
            return ""
        await share_btn.click(timeout=3000)
        await page.wait_for_timeout(1500)
        url = await page.evaluate("""() => {
            for (const inp of document.querySelectorAll('input')) {
                if (inp.value && inp.value.includes('mapy.com/s/')) return inp.value;
            }
            return '';
        }""")
        close_btn = page.locator("button.close").first
        if await close_btn.count():
            await close_btn.click(timeout=1000)
        else:
            await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
        if not url:
            print(f"    [share] dialog opened but no URL found for folder {fi}")
        return url
    except Exception as exc:
        print(f"    [share] exception for folder {fi}: {exc}")
        await page.keyboard.press("Escape")
        return ""


async def run(types_mode: bool = False) -> None:
    if not FOLDERS_FILE.exists():
        print("folders.json not found — run scrape_folders.py first")
        return

    with open(FOLDERS_FILE, encoding="utf-8") as f:
        folders_ctrl: list[dict] = json.load(f)["folders"]

    # Load or init mapy_data.json
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            mapy_data = json.load(f)
    else:
        mapy_data = {"folders": []}

    # Build lookup for merging: folder_name -> {map_name -> deque of map_dicts}
    # Using deque to correctly handle folders where multiple maps share the same name.
    data_lookup: dict[str, dict[str, deque]] = {}
    for fo in mapy_data["folders"]:
        d: dict[str, deque] = {}
        for m in fo["maps"]:
            d.setdefault(m["name"], deque()).append(m)
        data_lookup[fo["name"]] = d

    # Count total work
    headless    = True  if types_mode else HEADLESS
    screenshots = False if types_mode else TAKE_SCREENSHOTS

    if types_mode:
        total_work = sum(len(fo["maps"]) for fo in folders_ctrl)
    else:
        total_work = sum(
            len(fo["maps"]) if fo["include"] == "Y"
            else 1 if fo["include"] == "F"
            else sum(1 for m in fo["maps"] if m["include"] == "Y")
            for fo in folders_ctrl
        )
    if total_work == 0:
        print("Nothing to scrape — all include=N.")
        print("Edit folders.json to mark folders or maps include=Y, then re-run.")
        return

    print(f"Maps to scrape: {total_work}  (screenshots: {'on' if screenshots else 'off'})")

    cookies = read_firefox_cookies(FIREFOX_PROFILE)
    print(f"Loaded {len(cookies)} cookies")

    done = 0
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        print(f"Navigating to {MAPY_URL} ...")
        await page.goto(MAPY_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("ul.folders.sortable", timeout=20000)
        await page.wait_for_timeout(1000)

        for fi, folder_ctrl in enumerate(folders_ctrl):
            folder_name = folder_ctrl["name"]
            folder_include = folder_ctrl["include"]

            # Which map indices to process?
            if types_mode or folder_include == "Y":
                maps_to_scrape = set(range(len(folder_ctrl["maps"])))
            elif folder_include == "F":
                maps_to_scrape = set()      # folder screenshot only
            else:
                maps_to_scrape = {mi for mi, m in enumerate(folder_ctrl["maps"]) if m["include"] == "Y"}

            if not maps_to_scrape and folder_include != "F":
                print(f"\n[{fi+1}/{len(folders_ctrl)}] {folder_name}  (skip)")
                continue

            label = "folder only" if folder_include == "F" else f"{len(maps_to_scrape)} maps"
            print(f"\n[{fi+1}/{len(folders_ctrl)}] {folder_name}  ({label})")

            # Return to main page before opening folder
            if page.url != MAPY_URL:
                await page.goto(MAPY_URL, wait_until="networkidle", timeout=20000)
                await page.wait_for_selector("ul.folders.sortable", timeout=10000)
                await page.wait_for_timeout(600)

            # Ensure folder entry exists in mapy_data
            if folder_name not in data_lookup:
                data_lookup[folder_name] = {}
                mapy_data["folders"].append({
                    "name": folder_name, "share_link": "", "embed_src": "", "maps": []
                })
            mapy_folder = next(fo for fo in mapy_data["folders"] if fo["name"] == folder_name)

            # Folder share link — get BEFORE opening folder (opts works best on collapsed list)
            folder_share = await get_folder_share_url(page, fi)
            if folder_share:
                mapy_folder["share_link"] = folder_share
                print(f"  [folder share] {folder_share}")
            # Restore main page if opts dialog navigated away
            if page.url != MAPY_URL:
                await page.goto(MAPY_URL, wait_until="networkidle", timeout=20000)
                await page.wait_for_selector("ul.folders.sortable", timeout=10000)
                await page.wait_for_timeout(600)

            # Open folder
            await page.locator("li.folder").nth(fi).locator("div.bar h2.title").first.click()
            await page.wait_for_timeout(1000)
            try:
                await page.wait_for_selector("ul.items.sortable", timeout=8000)
            except Exception:
                print("  Could not open folder — skipping")
                continue

            folder_url = page.url

            # Read all map names + descriptions before any clicking (avoids stale reads)
            list_count = await page.locator("ul.items.sortable li.item").count()
            if types_mode or folder_include == "Y":
                maps_to_scrape = set(range(list_count))
            list_meta: list[dict] = []
            for mi in range(list_count):
                item = page.locator("ul.items.sortable li.item").nth(mi)
                name_el = item.locator("h2.title.overflow-ellipsis").first
                desc_el = item.locator("h3.desc.overflow-ellipsis").first
                name = (await name_el.inner_text()).strip() if await name_el.count() else ""
                desc = (await desc_el.inner_text()).strip() if await desc_el.count() else ""
                type_ = await detect_type_from_item(page, mi)
                list_meta.append({"name": name, "description": desc, "type": type_})

            # Folder note (lives globally on page, not inside li.folder)
            # Also saved as baseline so map notes can be distinguished from it
            folder_note_el = page.locator(".user-note__text").first
            folder_note_baseline = ""
            if await folder_note_el.count():
                folder_note_baseline = (await folder_note_el.inner_text()).strip()
                if folder_note_baseline:
                    mapy_folder["note"] = folder_note_baseline

            # Folder-level screenshot (all routes visible)
            if screenshots:
                await page.wait_for_timeout(FOLDER_SCREENSHOT_EXTRA_WAIT)  # extra wait for all routes to render
                folder_map_img = await take_map_screenshot(page, f"folder_{fi}")
                if folder_map_img:
                    mapy_folder["screenshot"] = folder_map_img
                    print(f"  [folder screenshot]")

            # Return to folder URL if context menu navigated away
            if page.url != folder_url:
                await page.goto(folder_url, wait_until="networkidle", timeout=20000)
                await page.wait_for_selector("ul.items.sortable", timeout=8000)
                await page.wait_for_timeout(600)

            # Process each map
            for mi in sorted(maps_to_scrape):
                if mi >= list_count:
                    print(f"  [{mi+1}] index out of range — skipping")
                    continue

                meta = list_meta[mi]
                ctrl_name = folder_ctrl["maps"][mi]["name"] if mi < len(folder_ctrl["maps"]) else ""
                map_name = meta["name"] or ctrl_name or f"Map {mi+1}"
                done += 1

                # Return to folder URL before each map click
                if page.url != folder_url:
                    await page.goto(folder_url, wait_until="networkidle", timeout=20000)
                    try:
                        await page.wait_for_selector("ul.items.sortable", timeout=8000)
                    except Exception:
                        print(f"  [{mi+1}] {map_name}  could not restore folder — skipping")
                        continue
                    await page.wait_for_timeout(600)

                await page.locator("ul.items.sortable li.item").nth(mi).click()
                await page.wait_for_timeout(1500)

                # Map note lives globally on page after item is selected.
                # Guard: if it matches the folder's note the map has no note of its own.
                map_note_el = page.locator(".user-note__text").first
                map_note_raw = (await map_note_el.inner_text()).strip() if await map_note_el.count() else ""
                map_note = map_note_raw if map_note_raw != folder_note_baseline else ""

                sl, es = await get_share_urls(page)

                # Screenshots — navigate to share URL for a clean per-route view
                # Fall back to previously stored link if extraction failed this run
                candidates = data_lookup.get(folder_name, {}).get(map_name, deque())
                existing_entry = next((c for c in candidates if c.get("share_link") == sl and sl), None) \
                                 or (candidates[0] if candidates else {})
                shot_url = sl or existing_entry.get("share_link", "")

                map_img, elev_img = "", ""
                if TAKE_SCREENSHOTS and shot_url:
                    share_code = shot_url.rstrip("/").split("/")[-1]
                    await page.goto(shot_url, wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(2000)
                    map_img  = await take_map_screenshot(page, share_code)
                    elev_img = await take_elevation_screenshot(page, share_code)
                    # Return to folder for next map
                    await page.goto(folder_url, wait_until="networkidle", timeout=20000)
                    try:
                        await page.wait_for_selector("ul.items.sortable", timeout=8000)
                    except Exception:
                        pass
                    await page.wait_for_timeout(600)

                print(f"  [{mi+1}] {map_name}  {sl or '(no link)'}  "
                      f"{'[map]' if map_img else ''}{'[elev]' if elev_img else ''}  [{done}/{total_work}]")

                # Upsert into mapy_data
                # For duplicate map names: match by share_link first, then consume first available.
                q = data_lookup[folder_name].get(map_name, deque())
                if sl:
                    m = next((c for c in q if c.get("share_link") == sl), None)
                    if m:
                        q.remove(m)
                    elif q:
                        m = q.popleft()
                    else:
                        m = None
                elif q:
                    m = q.popleft()
                else:
                    m = None

                if m is not None:
                    if meta["description"]:
                        m["description"] = meta["description"]
                        m["summary"] = meta["description"]
                    if meta["type"]:
                        m["type"] = meta["type"]
                    if map_note:
                        m["note"] = map_note
                    if sl:
                        m["share_link"] = sl
                    if es:
                        m["embed_src"] = es
                    if map_img:
                        m["screenshot"] = map_img
                    if elev_img:
                        m["elevation_img"] = elev_img
                else:
                    new_map = {
                        "name": map_name,
                        "description": meta["description"],
                        "type": meta["type"],
                        "note": map_note,
                        "share_link": sl,
                        "embed_src": es,
                        "points": [],
                        "summary": meta["description"],
                        "elevation_text": "",
                        "screenshot": map_img,
                        "elevation_img": elev_img,
                    }
                    mapy_folder["maps"].append(new_map)
                    data_lookup[folder_name].setdefault(map_name, deque()).append(new_map)

            # Save mapy_data.json after each folder
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(mapy_data, f, ensure_ascii=False, indent=2)

            # Reset this folder's include flags to N (safe for interrupts)
            if not types_mode and folder_ctrl["include"] in ("Y", "F"):
                folder_ctrl["include"] = "N"
                for m in folder_ctrl["maps"]:
                    m["include"] = "N"
                with open(FOLDERS_FILE, "w", encoding="utf-8") as f:
                    json.dump({"folders": folders_ctrl}, f, ensure_ascii=False, indent=2)

        await browser.close()

    with_links = sum(1 for fo in mapy_data["folders"] for m in fo["maps"] if m.get("share_link"))
    with_imgs  = sum(1 for fo in mapy_data["folders"] for m in fo["maps"] if m.get("screenshot"))
    total_maps = sum(len(fo["maps"]) for fo in mapy_data["folders"])
    print(f"\nDone. {with_links}/{total_maps} maps with share links, {with_imgs} with screenshots.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--types", action="store_true",
                        help="Headless pass: update type/note for all maps, no screenshots")
    args = parser.parse_args()
    asyncio.run(run(types_mode=args.types))
