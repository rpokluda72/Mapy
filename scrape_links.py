#!/usr/bin/env python3
"""
Second-pass script: navigate to each map, click Sdílet (Share), extract URLs.
Reads existing mapy_data.json, fills in share_link / embed_src, saves back.

Usage:
    python scrape_links.py
"""
import asyncio
import json
import re
import shutil
import sqlite3
import tempfile
import os
from pathlib import Path

from playwright.async_api import async_playwright, Page

FIREFOX_PROFILE = Path(
    r"C:\Users\roman\AppData\Roaming\Mozilla\Firefox\Profiles"
    r"\3yclgs3h.dev-edition-default"
)
MAPY_URL = "https://mapy.com/en/turisticka?moje-mapy&cat=mista-trasy"
DATA_FILE = Path(__file__).parent / "mapy_data.json"
HEADLESS = False
FORCE_RESHARE = True   # revisit maps that already have links to enable public sharing
TEST_FOLDERS = 2       # set to 0 to process all folders


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
    """
    Click the Share (Sdílet) button and extract share link + embed src.
    Returns (share_link, embed_src). Falls back to share_link for embed if needed.
    """
    share_link = ""
    embed_src = ""

    # Click Share button — use .filter() which reliably matches partial text
    share_btn = page.locator("button").filter(has_text="dílet").first
    if not await share_btn.count():
        return "", ""

    try:
        await share_btn.click(timeout=5000)
        await page.wait_for_timeout(1200)
    except Exception as e:
        return "", ""

    # Enable public sharing if the "Sdílet s ostatními" toggle is off
    toggle = page.locator("label.switch input[type='checkbox']").first
    if await toggle.count():
        try:
            if not await toggle.is_checked():
                await toggle.check()
                await page.wait_for_timeout(600)
        except Exception:
            pass

    # Extract share URL via JS — input.value is a DOM property, not HTML attribute
    share_link = await page.evaluate("""() => {
        for (const inp of document.querySelectorAll('input')) {
            if (inp.value && inp.value.includes('mapy.com/s/')) return inp.value;
        }
        return '';
    }""")

    # Try embed tab ("Vložit mapu do vlastních stránek")
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

    # Use share_link as embed fallback
    if share_link and not embed_src:
        embed_src = share_link

    return share_link, embed_src


async def run() -> None:
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    cookies = read_firefox_cookies(FIREFOX_PROFILE)
    print(f"Loaded {len(cookies)} cookies")

    total = sum(len(fo["maps"]) for fo in data["folders"])
    done = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        print(f"Navigating to {MAPY_URL} ...")
        await page.goto(MAPY_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("ul.folders.sortable", timeout=20000)
        await page.wait_for_timeout(1000)

        folders_to_process = data["folders"][:TEST_FOLDERS] if TEST_FOLDERS else data["folders"]
        for fi, folder in enumerate(folders_to_process):
            print(f"\n[{fi+1}/{len(data['folders'])}] {folder['name']}  ({len(folder['maps'])} maps)")

            # Restore main page before each folder
            if page.url != MAPY_URL:
                await page.goto(MAPY_URL, wait_until="networkidle", timeout=20000)
                await page.wait_for_selector("ul.folders.sortable", timeout=10000)
                await page.wait_for_timeout(800)

            # Open folder
            await page.locator("li.folder").nth(fi).locator("div.bar h2.title").first.click()
            await page.wait_for_timeout(1000)
            try:
                await page.wait_for_selector("ul.items.sortable", timeout=8000)
            except Exception:
                print("  Could not open folder — skipping")
                continue

            folder_url = page.url

            for mi, map_data in enumerate(folder["maps"]):
                done += 1

                if not FORCE_RESHARE and (map_data.get("share_link") or map_data.get("embed_src")):
                    print(f"  [{mi+1}/{len(folder['maps'])}] {map_data['name']}  (skip — already has link)")
                    continue

                # Return to folder list
                if page.url != folder_url:
                    await page.goto(folder_url, wait_until="networkidle", timeout=20000)
                    try:
                        await page.wait_for_selector("ul.items.sortable", timeout=8000)
                    except Exception:
                        print(f"  [{mi+1}] could not restore folder list — skipping")
                        continue
                    await page.wait_for_timeout(600)

                await page.locator("ul.items.sortable li.item").nth(mi).click()
                await page.wait_for_timeout(1500)

                sl, es = await get_share_urls(page)
                map_data["share_link"] = sl
                map_data["embed_src"] = es

                print(f"  [{mi+1}/{len(folder['maps'])}] {map_data['name']}  {sl or '(none)'}  [{done}/{total}]")

        await browser.close()

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    with_links = sum(1 for fo in data["folders"] for m in fo["maps"] if m.get("share_link"))
    print(f"\nSaved. Maps with share link: {with_links}/{total}")


if __name__ == "__main__":
    asyncio.run(run())
