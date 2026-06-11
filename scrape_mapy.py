#!/usr/bin/env python3
"""
Scrape saved maps from mapy.com (Moje Mapy) and save to mapy_data.json.

Reads cookies from your local Firefox profile so you don't need to log in again.
If Firefox is running, the script copies cookies.sqlite to a temp file first.

Usage:
    python scrape_mapy.py
"""
import asyncio
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright, Page

# ── Config ──────────────────────────────────────────────────────────────────
FIREFOX_PROFILE = Path(
    r"C:\Users\roman\AppData\Roaming\Mozilla\Firefox\Profiles"
    r"\3yclgs3h.dev-edition-default"
)
MAPY_URL = "https://mapy.com/en/turisticka?moje-mapy&cat=mista-trasy"
OUTPUT_FILE = Path(__file__).parent / "mapy_data.json"
HEADLESS = False  # set True to run without browser window


# ── Cookie helpers ───────────────────────────────────────────────────────────

def read_firefox_cookies(profile_dir: Path, domain_filter: str = "mapy.com") -> list[dict]:
    cookies_db = profile_dir / "cookies.sqlite"
    if not cookies_db.exists():
        raise FileNotFoundError(f"cookies.sqlite not found: {cookies_db}")

    # Copy to temp — avoids SQLite lock when Firefox is running
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(tmp_fd)
    shutil.copy2(cookies_db, tmp_path)

    try:
        conn = sqlite3.connect(tmp_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT name, value, host, path, expiry, isSecure, isHttpOnly, sameSite "
            "FROM moz_cookies WHERE host LIKE ?",
            (f"%{domain_filter}%",),
        )
        rows = cur.fetchall()
        conn.close()
    finally:
        os.unlink(tmp_path)

    same_site_map = {0: "None", 1: "Lax", 2: "Strict"}
    return [
        {
            "name": r["name"],
            "value": r["value"],
            "domain": r["host"],
            "path": r["path"],
            "expires": int(r["expiry"] / 1000) if r["expiry"] > 1e10 else (r["expiry"] if r["expiry"] > 0 else -1),
            "secure": bool(r["isSecure"]),
            "httpOnly": bool(r["isHttpOnly"]),
            "sameSite": same_site_map.get(r["sameSite"], "None"),
        }
        for r in rows
    ]


# ── Share-link helpers ───────────────────────────────────────────────────────

async def _extract_urls_from_page(page: Page) -> tuple[str, str]:
    """
    Pull share-link + embed-src from any currently visible inputs on the page.
    Returns ("", "") if none found.
    """
    share_link = ""
    embed_src = ""

    # Direct-link inputs
    for inp in await page.locator("input[value*='mapy.com/s/']").all():
        val = (await inp.get_attribute("value") or "").strip()
        if "mapy.com/s/" in val and not val.startswith("<"):
            share_link = val
            break

    # Embed-code inputs / textareas
    for sel in ["input[value*='<iframe']", "textarea"]:
        for el in await page.locator(sel).all():
            val = (await el.get_attribute("value") or await el.inner_text() or "").strip()
            m = re.search(r'src="(https://mapy\.com/s/[^"]+)"', val)
            if m:
                embed_src = m.group(1)
                break
        if embed_src:
            break

    return share_link, embed_src


async def _click_share_and_extract(page: Page, label: str) -> tuple[str, str]:
    """
    Open the three-dots opts menu, click Share, then extract URLs from the dialog.
    label is used only for log messages.
    """
    share_link = ""
    embed_src = ""

    # Hover the active/selected list item so opts appears
    for sel in ["li.item.active", "li.item.selected", "li.item.open"]:
        active = page.locator(sel).first
        if await active.count():
            await active.hover()
            await page.wait_for_timeout(300)
            break

    opts_btn = page.locator(
        "li.item.active span.opts, li.item.selected span.opts, li.item.open span.opts, "
        "span.opts"
    ).first
    if not await opts_btn.count():
        return share_link, embed_src

    await opts_btn.click()
    try:
        await page.wait_for_selector("div.ui-popover.ui-contextmenu", timeout=3000)
    except Exception:
        return share_link, embed_src

    await page.wait_for_timeout(400)

    # Find the Share button in the context menu
    share_btn = None
    for btn in await page.locator("button.ui-contextmenuitem").all():
        text = (await btn.inner_text()).strip().lower()
        if any(w in text for w in ["share", "sdíl", "link", "send"]):
            share_btn = btn
            break

    if not share_btn:
        await page.keyboard.press("Escape")
        return share_link, embed_src

    await share_btn.click()
    await page.wait_for_timeout(1500)

    # First grab the plain share link
    share_link, _ = await _extract_urls_from_page(page)

    # Switch to embed tab if available
    embed_tab = None
    for sel in ["button:has-text('Embed')", "a:has-text('Embed')", "[data-tab='embed']",
                "button:has-text('Vložit')", "label:has-text('Embed')"]:
        el = page.locator(sel).first
        if await el.count():
            embed_tab = el
            break

    if embed_tab:
        await embed_tab.click()
        await page.wait_for_timeout(600)
        _, embed_src = await _extract_urls_from_page(page)

    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)
    return share_link, embed_src


async def get_share_data(page: Page, label: str) -> tuple[str, str]:
    """Try cheap extraction first; fall back to UI clicking."""
    share_link, embed_src = await _extract_urls_from_page(page)
    if share_link and embed_src:
        return share_link, embed_src
    try:
        sl, es = await _click_share_and_extract(page, label)
        share_link = share_link or sl
        embed_src = embed_src or es
    except Exception as e:
        print(f"    [WARN] share data for '{label}': {e}")
    return share_link, embed_src


# ── Map detail helpers ───────────────────────────────────────────────────────

async def scrape_map_details(page: Page) -> dict:
    try:
        await page.wait_for_selector(
            "div.route-items, div.route-summary", timeout=6000
        )
    except Exception:
        return {"points": [], "summary": "", "elevation_text": ""}

    points = []
    try:
        for pt in await page.locator("div.route-items li, div.route-items .route-item").all():
            t = (await pt.inner_text()).strip()
            if t:
                points.append(t)
    except Exception:
        pass

    summary = ""
    try:
        parts = []
        for el in await page.locator("div.route-summary").all():
            t = (await el.inner_text()).strip()
            if t:
                parts.append(t)
        summary = " | ".join(parts)
    except Exception:
        pass

    elevation_text = ""
    try:
        el = page.locator("div.module-content.route-height-profile").first
        if await el.count():
            elevation_text = (await el.inner_text()).strip()[:400]
    except Exception:
        pass

    return {"points": points, "summary": summary, "elevation_text": elevation_text}


def detect_type(cls: str) -> str:
    cls = cls.lower()
    if any(w in cls for w in ["bike", "cycl", "bicycle", "cykl"]):
        return "bike"
    if any(w in cls for w in ["hik", "walk", "foot", "trek", "turist", "péší"]):
        return "hiking"
    if any(w in cls for w in ["car", "driv", "auto", "road"]):
        return "car"
    return ""


# ── Main scrape ──────────────────────────────────────────────────────────────

async def scrape() -> dict:
    print("Reading Firefox cookies …")
    cookies = read_firefox_cookies(FIREFOX_PROFILE)
    print(f"  Loaded {len(cookies)} cookie(s) for mapy.com")

    result: dict = {"folders": []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        await context.add_cookies(cookies)
        page = await context.new_page()

        print(f"Navigating to {MAPY_URL} …")
        await page.goto(MAPY_URL, wait_until="networkidle", timeout=30000)

        try:
            await page.wait_for_selector("ul.folders.sortable", timeout=20000)
        except Exception:
            print("ERROR: folders list not found — are you logged in?")
            print("  Current URL:", page.url)
            await browser.close()
            return result

        await page.wait_for_timeout(1500)

        # Pass 1: collect folder names without clicking anything
        folder_count = await page.locator("li.folder").count()
        folder_names = []
        for fi in range(folder_count):
            try:
                name = (await page.locator("li.folder").nth(fi).locator("div.bar h2.title").first.inner_text()).strip()
            except Exception:
                name = f"Folder {fi + 1}"
            folder_names.append(name)
        print(f"Found {folder_count} folder(s)\n")

        for fi, folder_name in enumerate(folder_names):
            print(f"[{fi+1}/{folder_count}] Folder: {folder_name}")

            folder_data: dict = {
                "name": folder_name,
                "share_link": "",
                "embed_src": "",
                "maps": [],
            }

            # Navigate back to main page before each folder to avoid stale elements
            if page.url != MAPY_URL:
                await page.goto(MAPY_URL, wait_until="networkidle", timeout=20000)
                await page.wait_for_selector("ul.folders.sortable", timeout=10000)
                await page.wait_for_timeout(800)

            # Open the folder by index
            await page.locator("li.folder").nth(fi).locator("div.bar h2.title").first.click()
            await page.wait_for_timeout(1500)
            try:
                await page.wait_for_selector("ul.items.sortable", timeout=8000)
            except Exception:
                print(f"  Could not open folder — skipping")
                result["folders"].append(folder_data)
                continue

            # Folder-level share
            folder_share, folder_embed = await get_share_data(page, folder_name)
            folder_data["share_link"] = folder_share
            folder_data["embed_src"] = folder_embed

            # Save folder URL so we can return to the list after each map click
            folder_url = page.url

            # --- Pass 1: collect basic info from the list (before any map clicks) ---
            map_infos = []
            map_count = await page.locator("ul.items.sortable li.item").count()
            print(f"  {map_count} map(s)")

            for mi in range(map_count):
                el = page.locator("ul.items.sortable li.item").nth(mi)
                try:
                    name = (await el.locator("div.text-cover h2.title, h2.title").first.inner_text()).strip()
                except Exception:
                    name = f"Map {mi + 1}"
                try:
                    desc = (await el.locator("div.text-cover h3.desc, h3.desc").first.inner_text()).strip()
                except Exception:
                    desc = ""
                map_type = ""
                try:
                    li_cls = await el.get_attribute("class") or ""
                    map_type = detect_type(li_cls)
                    if not map_type:
                        icon_el = el.locator("[class*='icon']").first
                        if await icon_el.count():
                            map_type = detect_type(await icon_el.get_attribute("class") or "")
                except Exception:
                    pass
                map_infos.append({"name": name, "description": desc, "type": map_type})

            # --- Pass 2: click each map, extract details + share links ---
            for mi, info in enumerate(map_infos):
                print(f"  [{mi+1}/{map_count}] {info['name']}  {info['description']}  type={info['type'] or '?'}")

                map_data: dict = {
                    "name": info["name"],
                    "description": info["description"],
                    "type": info["type"],
                    "share_link": "",
                    "embed_src": "",
                    "points": [],
                    "summary": info["description"],
                    "elevation_text": "",
                }

                # Navigate back to the folder list, then click map by index
                if page.url != folder_url:
                    await page.goto(folder_url, wait_until="networkidle", timeout=20000)
                    try:
                        await page.wait_for_selector("ul.items.sortable", timeout=8000)
                    except Exception:
                        print(f"    [WARN] could not restore folder list, skipping map")
                        folder_data["maps"].append(map_data)
                        continue
                    await page.wait_for_timeout(800)

                await page.locator("ul.items.sortable li.item").nth(mi).click()
                await page.wait_for_timeout(2500)

                details = await scrape_map_details(page)
                map_data["points"] = details["points"]
                if details["summary"]:
                    map_data["summary"] = details["summary"]
                map_data["elevation_text"] = details["elevation_text"]

                sl, es = await get_share_data(page, info["name"])
                map_data["share_link"] = sl
                map_data["embed_src"] = es

                folder_data["maps"].append(map_data)

            result["folders"].append(folder_data)

        await browser.close()

    return result


if __name__ == "__main__":
    data = asyncio.run(scrape())

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSaved: {OUTPUT_FILE}")
    for folder in data["folders"]:
        print(f"  {folder['name']}: {len(folder['maps'])} map(s)")
