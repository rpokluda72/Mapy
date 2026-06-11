#!/usr/bin/env python3
"""
Step 1: Fast scan — collect folder and map names from mapy.com Moje Mapy.
Creates/updates folders.json with include=Y/N flags.

  New folder or map  →  include=Y  (needs scraping)
  Already seen       →  include=N  (skip)

Run this first, optionally edit folders.json, then run scrape_details.py.
"""
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
DATA_FILE    = Path(__file__).parent / "mapy_data.json"
HEADLESS = False


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


async def run() -> None:
    # Load previous folders.json for comparison
    prev: dict[str, dict] = {}  # folder_name -> {include, maps: {name -> include}}
    if FOLDERS_FILE.exists():
        with open(FOLDERS_FILE, encoding="utf-8") as f:
            old = json.load(f)
        for fo in old["folders"]:
            prev[fo["name"]] = {
                "include": fo.get("include", "N"),
                "maps": {m["name"]: m.get("include", "N") for m in fo.get("maps", [])},
            }
        print(f"Previous folders.json: {len(prev)} folders")
    else:
        print("No previous folders.json — all folders will be marked include=Y")

    cookies = read_firefox_cookies(FIREFOX_PROFILE)
    print(f"Loaded {len(cookies)} cookies")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        print(f"Navigating to {MAPY_URL} ...")
        await page.goto(MAPY_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("ul.folders.sortable", timeout=20000)
        await page.wait_for_timeout(1000)

        # Collect all folder names in one pass (no clicking needed)
        folder_count = await page.locator("li.folder").count()
        folder_names: list[str] = []
        for fi in range(folder_count):
            raw = await page.locator("li.folder").nth(fi).locator("div.bar h2.title").first.inner_text()
            folder_names.append(raw.strip())
        print(f"Found {folder_count} folders\n")

        folders = []
        for fi, folder_name in enumerate(folder_names):
            print(f"[{fi+1}/{folder_count}] {folder_name}", end="  ", flush=True)

            # Return to main page before each folder click
            if page.url != MAPY_URL:
                await page.goto(MAPY_URL, wait_until="networkidle", timeout=20000)
                await page.wait_for_selector("ul.folders.sortable", timeout=10000)
                await page.wait_for_timeout(600)

            # Click folder to expand map list
            await page.locator("li.folder").nth(fi).locator("div.bar h2.title").first.click()
            await page.wait_for_timeout(700)
            try:
                await page.wait_for_selector("ul.items.sortable", timeout=8000)
            except Exception:
                print("could not open — skipping")
                folder_include = "Y" if folder_name not in prev else prev[folder_name]["include"]
                folders.append({"name": folder_name, "include": folder_include, "maps": []})
                continue

            map_count = await page.locator("ul.items.sortable li.item").count()
            maps = []
            for mi in range(map_count):
                raw = await page.locator("ul.items.sortable li.item").nth(mi).locator("h2.title").first.inner_text()
                map_name = raw.strip()

                if folder_name not in prev:
                    map_include = "Y"
                elif map_name not in prev[folder_name]["maps"]:
                    map_include = "Y"
                else:
                    map_include = prev[folder_name]["maps"][map_name]

                maps.append({"name": map_name, "include": map_include})

            folder_include = "Y" if folder_name not in prev else prev[folder_name]["include"]
            new_count = sum(1 for m in maps if m["include"] == "Y")
            print(f"{map_count} maps, {new_count} pending")
            folders.append({"name": folder_name, "include": folder_include, "maps": maps})

        await browser.close()

    with open(FOLDERS_FILE, "w", encoding="utf-8") as f:
        json.dump({"folders": folders}, f, ensure_ascii=False, indent=2)

    folder_y = sum(1 for fo in folders if fo["include"] == "Y")
    map_y = sum(1 for fo in folders for m in fo["maps"] if m["include"] == "Y")
    print(f"\nSaved folders.json: {len(folders)} folders, {folder_y} folders + {map_y} maps marked include=Y")

    # Prune mapy_data.json: remove folders/maps no longer on mapy.com
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            mapy_data = json.load(f)

        live_folders = {fo["name"]: {m["name"] for m in fo["maps"]} for fo in folders}

        pruned_folders, removed_folders, removed_maps = [], [], []
        for fo in mapy_data["folders"]:
            if fo["name"] not in live_folders:
                removed_folders.append(fo["name"])
                continue
            live_maps = live_folders[fo["name"]]
            gone = [m["name"] for m in fo["maps"] if m["name"] not in live_maps]
            fo["maps"] = [m for m in fo["maps"] if m["name"] in live_maps]
            removed_maps.extend(f"{fo['name']} / {m}" for m in gone)
            pruned_folders.append(fo)
        mapy_data["folders"] = pruned_folders

        if removed_folders or removed_maps:
            print("\nPruned from mapy_data.json:")
            for name in removed_folders:
                print(f"  Removed folder: {name}")
            for name in removed_maps:
                print(f"  Removed map: {name}")
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(mapy_data, f, ensure_ascii=False, indent=2)
        else:
            print("mapy_data.json: nothing to prune")


if __name__ == "__main__":
    asyncio.run(run())
