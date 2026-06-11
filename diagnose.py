"""
Opens the first map, clicks the Share button, dumps the resulting dialog DOM.
"""
import asyncio, shutil, sqlite3, tempfile, os
from pathlib import Path
from playwright.async_api import async_playwright

FIREFOX_PROFILE = Path(
    r"C:\Users\roman\AppData\Roaming\Mozilla\Firefox\Profiles"
    r"\3yclgs3h.dev-edition-default"
)
MAPY_URL = "https://mapy.com/en/turisticka?moje-mapy&cat=mista-trasy"

def read_cookies(profile):
    db = profile / "cookies.sqlite"
    tmp_fd, tmp = tempfile.mkstemp(suffix=".sqlite")
    os.close(tmp_fd); shutil.copy2(db, tmp)
    conn = sqlite3.connect(tmp); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT name,value,host,path,expiry,isSecure,isHttpOnly,sameSite FROM moz_cookies WHERE host LIKE '%mapy.com%'").fetchall()
    conn.close(); os.unlink(tmp)
    sm = {0:"None",1:"Lax",2:"Strict"}
    return [{"name":r["name"],"value":r["value"],"domain":r["host"],"path":r["path"],
             "expires":int(r["expiry"]/1000) if r["expiry"]>1e10 else (r["expiry"] if r["expiry"]>0 else -1),
             "secure":bool(r["isSecure"]),"httpOnly":bool(r["isHttpOnly"]),"sameSite":sm.get(r["sameSite"],"None")} for r in rows]

async def main():
    cookies = read_cookies(FIREFOX_PROFILE)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(viewport={"width":1440,"height":900})
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        await page.goto(MAPY_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("ul.folders.sortable", timeout=20000)
        await page.wait_for_timeout(1000)

        # Open first folder, click first map
        await page.locator("li.folder").nth(0).locator("div.bar h2.title").first.click()
        await page.wait_for_selector("ul.items.sortable", timeout=8000)
        await page.wait_for_timeout(1000)
        print("Map URL before click:", page.url)
        await page.locator("ul.items.sortable li.item").nth(0).click()
        await page.wait_for_timeout(2500)
        print("Map URL after click :", page.url)

        # Try clicking the Share button
        share_btn = page.locator("button").filter(has_text="dílet").first
        cnt = await share_btn.count()
        print(f"\nShare button count: {cnt}")
        if cnt:
            print("Clicking Share...")
            await share_btn.click()
            await page.wait_for_timeout(2000)
            print("URL after Share click:", page.url)

            # Dump all inputs and textareas
            print("\n--- Inputs/Textareas after Share click ---")
            for el in await page.locator("input, textarea").all():
                try:
                    val = await el.get_attribute("value") or await el.inner_text() or ""
                    typ = await el.get_attribute("type") or "text"
                    vis = await el.is_visible()
                    if val or vis:
                        print(f"  type={typ} visible={vis} value={val[:120]!r}")
                except: pass

            # Dump all visible text in new elements
            print("\n--- All links containing mapy.com ---")
            result = await page.evaluate("""() => {
                const found = [];
                document.querySelectorAll('input, textarea, a, [class*="share"], [class*="link"], [class*="url"]').forEach(el => {
                    const val = el.value || el.href || el.textContent || '';
                    if (val && val.includes('mapy.com')) {
                        found.push({tag: el.tagName, cls: el.className.toString().substring(0,60), val: val.substring(0,150)});
                    }
                });
                return found;
            }""")
            for r in result:
                print(f"  <{r['tag']}> class={r['cls']!r} val={r['val']!r}")

            # Dump buttons visible after share click
            print("\n--- Buttons visible after Share click ---")
            for el in await page.locator("button").all():
                try:
                    txt = (await el.inner_text(timeout=300)).strip().replace("\n"," ")
                    vis = await el.is_visible()
                    cls = (await el.get_attribute("class") or "")[:60]
                    if txt and vis: print(f"  class={cls!r} text={txt!r}")
                except: pass

            # Full HTML of any new overlay/modal/panel
            print("\n--- New overlay/modal HTML (first 4000 chars) ---")
            overlay = await page.evaluate("""() => {
                const sels = [
                    '[class*="modal"]', '[class*="overlay"]', '[class*="dialog"]',
                    '[class*="share"]', '[class*="popup"]', '[class*="panel"]',
                    '[role="dialog"]', '[class*="Share"]'
                ];
                for (const s of sels) {
                    const el = document.querySelector(s);
                    if (el && el.offsetParent !== null) return s + ':\\n' + el.innerHTML.substring(0, 4000);
                }
                return '(no overlay found)';
            }""")
            print(overlay)

        input("\nPress Enter to close...")
        await browser.close()

asyncio.run(main())
