#!/usr/bin/env python3
"""Diagnose note selectors — opens one folder and prints what it finds."""
import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

FIREFOX_PROFILE = Path(
    r"C:\Users\roman\AppData\Roaming\Mozilla\Firefox\Profiles"
    r"\3yclgs3h.dev-edition-default"
)
MAPY_URL = "https://mapy.com/en/turisticka?moje-mapy&cat=mista-trasy"
FOLDERS_FILE = Path(__file__).parent / "folders.json"
HEADLESS = False  # visible so you can see what's happening


def read_firefox_cookies(profile_dir, domain="mapy.com"):
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
    return [{"name": r["name"], "value": r["value"], "domain": r["host"],
             "path": r["path"],
             "expires": int(r["expiry"] / 1000) if r["expiry"] > 1e10 else (r["expiry"] if r["expiry"] > 0 else -1),
             "secure": bool(r["isSecure"]), "httpOnly": bool(r["isHttpOnly"]),
             "sameSite": sm.get(r["sameSite"], "None")}
            for r in rows]


async def run():
    with open(FOLDERS_FILE, encoding="utf-8") as f:
        folders = json.load(f)["folders"]

    # Use first folder
    folder_name = folders[0]["name"]
    print(f"Testing with folder: {folder_name}\n")

    cookies = read_firefox_cookies(FIREFOX_PROFILE)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        await page.goto(MAPY_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("ul.folders.sortable", timeout=20000)
        await page.wait_for_timeout(1500)

        # Check folder note BEFORE clicking
        print("=== Folder note BEFORE opening ===")
        note = await page.locator("li.folder").first.locator("p.user-note__text").count()
        print(f"  p.user-note__text count: {note}")
        note2 = await page.locator("li.folder").first.locator("[class*='note']").count()
        print(f"  [class*='note'] count: {note2}")
        if note2:
            for i in range(note2):
                el = page.locator("li.folder").first.locator("[class*='note']").nth(i)
                cls = await el.get_attribute("class")
                txt = await el.inner_text()
                print(f"    [{i}] class='{cls}'  text='{txt[:80]}'")

        # Open folder
        await page.locator("li.folder").first.locator("div.bar h2.title").first.click()
        await page.wait_for_timeout(1000)
        await page.wait_for_selector("ul.items.sortable", timeout=8000)
        await page.wait_for_timeout(500)

        # Check folder note AFTER opening
        print("\n=== Folder note AFTER opening ===")
        note = await page.locator("li.folder").first.locator("p.user-note__text").count()
        print(f"  p.user-note__text count: {note}")
        note2 = await page.locator("li.folder").first.locator("[class*='note']").count()
        print(f"  [class*='note'] count: {note2}")
        if note2:
            for i in range(note2):
                el = page.locator("li.folder").first.locator("[class*='note']").nth(i)
                cls = await el.get_attribute("class")
                txt = await el.inner_text()
                print(f"    [{i}] class='{cls}'  text='{txt[:80]}'")

        # Check first map item
        print("\n=== First map item ===")
        item = page.locator("ul.items.sortable li.item").first
        note = await item.locator("p.user-note__text").count()
        print(f"  p.user-note__text count: {note}")
        note2 = await item.locator("[class*='note']").count()
        print(f"  [class*='note'] count: {note2}")
        if note2:
            for i in range(note2):
                el = item.locator("[class*='note']").nth(i)
                cls = await el.get_attribute("class")
                txt = await el.inner_text()
                print(f"    [{i}] class='{cls}'  text='{txt[:80]}'")

        # Dump ALL note-like elements on the page
        print("\n=== ALL [class*='note'] on page ===")
        all_notes = await page.locator("[class*='note']").count()
        print(f"  Total: {all_notes}")
        for i in range(min(all_notes, 20)):
            el = page.locator("[class*='note']").nth(i)
            cls = await el.get_attribute("class")
            txt = (await el.inner_text()).strip()[:80]
            print(f"  [{i}] class='{cls}'  text='{txt}'")

        input("\nPress Enter to close browser...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
