# Mapy.com Static Site Generator

Generates a self-contained static website from your saved maps on [mapy.com](https://mapy.com).

The site has a collapsible folder/map tree on the left and a detail panel on the right — showing a map screenshot, elevation chart, type icon, notes, and an "Open in mapy.com" button for each route.

## Requirements

- Python 3.x
- Firefox with an active mapy.com session (logged in)

## Setup

```
run install
```

## Commands

| Command | What it does |
|---|---|
| `run folders` | Scan mapy.com structure → `folders.json`; removes deleted items from `mapy_data.json` and their images |
| `run details` | Full scrape of `include=Y/F` items → screenshots, share links, notes → `mapy_data.json` |
| `run types` | Lightweight headless pass → updates `type` and `note` fields for already-scraped maps |
| `run build` | Generate `index.html` + `data.js` from `mapy_data.json` |
| `run serve` | Serve at `http://localhost:8000` (enables hide/restore and admin panel) |
| `run admin` | Open `admin.html` in browser (requires `run serve` to be running) |
| `run open` | Open `index.html` directly (filter works, hide/restore requires `run serve`) |
| `run all` | `folders` + `details` + `build` in one go |
| `run install` | Install Python dependencies (run once) |
| `run scrape` | **Deprecated** — old all-in-one scraper (`scrape_mapy.py`); use `run folders` + `run details` instead |
| `run links` | **Deprecated** — old share-link filler (`scrape_links.py`); use `run details` instead |

## Initial setup

```
run all
run serve
```

## What to run in common situations

### New folders or maps added on mapy.com
```
run folders    ← detects new items (include=Y), removes deleted ones from mapy_data.json
run details    ← scrapes only the new include=Y items
run build
```

### A map or folder was edited (name, description, note changed)
```
run folders                         ← refresh folders.json
# edit folders.json: set include=Y on the changed folder/map
run details
run build
```
Or for notes and types only (faster, no screenshots):
```
run types
run build
```

### A map or folder was deleted on mapy.com
```
run folders    ← removes deleted items from mapy_data.json and deletes their images
run build
```
> **Note:** `run details` does not remove deleted maps — always use `run folders` to sync deletions.

### You want to update map types or notes for all existing maps
```
run types      ← headless, ~1 min, no screenshots
run build
```

### You want to re-scrape a specific folder from scratch
1. Edit `folders.json` — set `"include": "Y"` on the folder (or use admin panel)
2. `run details`
3. `run build`

### The folder map image looks wrong (missing routes)
1. Set `"include": "F"` on the folder in the admin panel (click the folder's Y/N button until it shows **F**)
2. `run details` — navigates to the folder's share URL, retakes only the folder map screenshot, skips individual maps (fast)
3. `run build`

### You want to reorder folders or maps
1. `run serve`
2. Open `http://localhost:8000/admin.html`
3. In the **Folders** tab, use the **▲▼** buttons on each folder (or map within a folder) to reorder
4. Click **Save** — writes the new order to `folders.json` and automatically syncs it into `mapy_data.json`
5. `run build`

### You modified the HTML template (`templates/index.html.j2`)
```
run build
```

## Admin panel (`admin.html`)

The admin panel has two tabs: **Folders** (edit `include` flags and ordering) and **Data viewer** (browse scraped data, hide/restore).

### Two ways to open it

| Mode | URL | Use for |
|---|---|---|
| **Server** | `http://localhost:8000/admin.html` | Editing include flags and ordering — reads live `folders.json`, Save writes back to disk |
| **Static** | open `admin.html` directly as a file | Read-only browsing — loads data from `folders_data.js` / `data.js` snapshots baked by `run build` |

**Always use the server URL when editing.** The static version loads pre-built snapshots that may be out of date if `folders.json` was changed by the scraper or manually after the last `run build`.

### Editing include flags via admin

1. `run serve`
2. `run admin` (or open `http://localhost:8000/admin.html`)
3. Toggle Y/N/F flags, use **All Y** / **All N** per folder or globally
4. Click **Save** — writes `folders.json` immediately
5. `run details` / `run build` as needed

### Reordering folders and maps

In the **Folders** tab, each folder row and each map row has **▲▼** buttons (side-by-side) to move items up or down. Clicking **Save** writes the new order to `folders.json` and automatically syncs it into `mapy_data.json`. Then `run build` to regenerate the site with the new display order.

## Script dependencies — do not run concurrently

All scripts share the same output files and must run **sequentially**, never in parallel:

| Script | Reads | Writes |
|---|---|---|
| `scrape_folders.py` | mapy.com | `folders.json`, `mapy_data.json` |
| `scrape_details.py` | `folders.json` + mapy.com | `mapy_data.json`, `folders.json` (resets include flags) |
| `scrape_details.py --types` | `mapy_data.json` + mapy.com | `mapy_data.json` |
| `generate_site.py` | `mapy_data.json`, `folders.json` | `index.html`, `data.js`, `folders_data.js` |

Running two scrapers at once also opens two browsers on the same mapy.com session, which corrupts the DOM state for both.

Correct order: `folders` → `details` → `types` → `build`

## How `include` flags work

`folders.json` controls what gets (re-)scraped:

- **Folder `include=Y`** — scrape all maps in the folder, regardless of map-level flags
- **Folder `include=F`** — retake the folder map screenshot only; skip all individual maps
- **Folder `include=N`, map `include=Y`** — scrape only that specific map
- **Both `include=N`** — skip entirely

`run folders` sets new items to `Y` and keeps existing items at their current value.  
`run details` resets processed items back to `N` after each folder (safe to interrupt and resume).

## Files

| File | Purpose |
|---|---|
| `scrape_folders.py` | Fast scan — mapy.com structure → `folders.json`; prunes deleted items from `mapy_data.json` |
| `scrape_details.py` | Full scrape — screenshots, share links, notes → `mapy_data.json`; `--types` flag for headless type/note pass |
| `generate_site.py` | Generator — `mapy_data.json` → `index.html` + `data.js` |
| `server.py` | Local HTTP server with hide/restore API |
| `check_data.py` | Quick data inspector — prints summary stats from `mapy_data.json` |
| `diagnose.py` | Share-dialog debugger — opens first map, dumps Share dialog DOM |
| `diagnose_notes.py` | Note-selector debugger — probes note-related DOM selectors |
| `scrape_mapy.py` | **Deprecated** — original all-in-one scraper (replaced by `scrape_folders` + `scrape_details`) |
| `scrape_links.py` | **Deprecated** — old second-pass share-link filler (replaced by `scrape_details`) |
| `templates/index.html.j2` | Jinja2 HTML template |
| `folders.json` | Folder/map list with include flags (created by `run folders`) |
| `mapy_data.json` | Scraped data — screenshots, share links, notes, types (created by `run details`) |
| `images/` | Map and elevation screenshots (created by `run details`) |
| `index.html` | Final site output (created by `run build`) |
| `data.js` | Map data loaded by `index.html` (created by `run build`) |
| `folders_data.js` | Snapshot of `folders.json` for static admin (created by `run build`) |
| `admin.html` | Admin panel — edit include flags, browse scraped data |
| `run.bat` | Command runner (Windows) |

## Script details

Each script can be run directly with `python <script>.py`. Below is a full reference.

### `scrape_folders.py` — folder/map structure scan

```
python scrape_folders.py
```

**Source:** mapy.com (live browser session via Firefox cookies)  
**Background:** Fast first-pass scraper. Opens a Chromium window, reads the folder and map list from the "Moje Mapy" sidebar, and records names, descriptions, and type icons. Does not open individual maps or take screenshots.  
**Result:** Writes (or updates) `folders.json` — the list of all folders and their maps with `include` flags. New items default to `include=Y`; existing items keep their current flag. Items no longer present on mapy.com are removed from `mapy_data.json`.

---

### `scrape_details.py` — full detail scrape

```
python scrape_details.py
```

**Source:** `folders.json` (which items to process) + mapy.com (live browser session)  
**Background:** Processes items marked `include=Y` or `include=F`. For `include=Y`: clicks into each map, takes a map screenshot and elevation-chart screenshot, reads the route note, opens the Share dialog to extract the share link and embed URL. For `include=F`: takes only the folder map screenshot by navigating to the folder's share URL (skips individual maps — useful when the folder image is missing routes or is outdated). Resets `include` to `N` after each folder so the run is safe to interrupt and resume.

Folder screenshot filenames use the folder's share URL code (e.g. `images/juromelujo.png`), the same scheme as individual map screenshots. This keeps filenames stable if folders are reordered.

**Result:** Merges data into `mapy_data.json`; saves screenshots to `images/`.

---

### `scrape_details.py --types` — type and note refresh

```
python scrape_details.py --types
```

**Source:** `mapy_data.json` (existing scraped data) + mapy.com (live browser session, headless)  
**Background:** Lightweight headless pass — re-reads the map type icon and user note for every map without retaking screenshots. Use this when you only changed a note or type on mapy.com and don't want to wait for a full screenshot pass.  
**Result:** Updates `type` and `note` fields in `mapy_data.json` in-place. Does not reset `include` flags.

---

### `generate_site.py` — site generator

```
python generate_site.py
```

**Source:** `mapy_data.json`, `folders.json`, `templates/index.html.j2`  
**Background:** Pure Python, no browser. Renders the Jinja2 template with all scraped data and writes the final static site.  
**Result:** `index.html` (the site), `data.js` (all map data as a JS module), `folders_data.js` (snapshot of `folders.json` for the static admin panel).

---

### `server.py` — local HTTP server

```
python server.py
```

**Source:** local files (`index.html`, `data.js`, `admin.html`, `folders.json`, `mapy_data.json`)  
**Background:** Serves the static site at `http://localhost:8000`. Uses HTTP/1.0 (no keep-alive) so Ctrl+C exits immediately. Sends `Cache-Control: no-store` for HTML, JSON, JS, and PNG files so browsers always fetch the latest version. Does not auto-open a browser on start. Exposes a small API:
- `POST /api/hide` — toggle hidden flag in `mapy_data.json`, then regenerates site
- `POST /api/folders` — save `folders.json` with new flags or ordering; automatically syncs folder and map order into `mapy_data.json`

**Result:** No file changes on its own — runs until interrupted with Ctrl+C.

---

### `check_data.py` — data inspector

```
python check_data.py
```

**Source:** `mapy_data.json`  
**Background:** Read-only, instant, no browser. Prints a quick health check: how many folders and maps are in the JSON, how many have share/embed links, how many have route points, and a sample entry for the first map.  
**Result:** Console output only, no files changed. Useful after scraping to confirm data looks complete.

Example output:
```
Folders : 5
Maps    : 47
With embed/share link: 45
With points          : 38

Sample - TJ Tatry-Gorce 2026 / Turbacz:
  share_link: 'https://mapy.com/s/...'
  embed_src : 'https://mapy.com/s/...'
  points    : ['Start', 'Turbacz', 'Finish']
  summary   : 'Route 14.3 km • 5:00 h'
```

---

### `diagnose.py` — share-dialog debugger

```
python diagnose.py
```

**Source:** mapy.com (live browser session via Firefox cookies)  
**Background:** Development/debugging tool. Opens a visible browser, navigates to the first folder and first map, clicks the Share button, and dumps the resulting dialog DOM — all inputs, all buttons, all overlay HTML, and all elements with mapy.com links. Pauses and waits for Enter before closing the browser so you can inspect the page.  
**Result:** Console output only. Use this when `share_link` / `embed_src` extraction stops working (e.g., after a mapy.com UI update) to find the right selectors.

---

### `diagnose_notes.py` — note-selector debugger

```
python diagnose_notes.py
```

**Source:** `folders.json` (to pick the first folder by name) + mapy.com (live browser session)  
**Background:** Development/debugging tool. Opens the first folder and probes all note-related DOM selectors (`p.user-note__text`, `[class*='note']`) before and after clicking to open the folder, and then for the first map item. Dumps class names and text content of every matching element. Pauses for Enter before closing.  
**Result:** Console output only. Use this when note extraction returns empty to understand what selectors the current mapy.com DOM uses.

---

### Deprecated scripts

These are kept for reference but replaced by the two-phase `folders` + `details` workflow:

#### `scrape_mapy.py` — original all-in-one scraper

```
python scrape_mapy.py
```

**Source:** mapy.com (live browser session via Firefox cookies)  
**Background:** First generation scraper. Reads Firefox cookies directly from the profile, then in a single pass collects folder/map names, route details (waypoints, summary, elevation text), and share links for every map. Slower than the split approach because it can't skip already-scraped items.  
**Result:** Overwrites `mapy_data.json` with the full data structure.

#### `scrape_links.py` — old share-link filler

```
python scrape_links.py
```

**Source:** `mapy_data.json` (existing data) + mapy.com (live browser session)  
**Background:** Was used as a second pass after `scrape_mapy.py` to fill in missing share links. Also enables the public-sharing toggle on maps that had it turned off. Controlled by `FORCE_RESHARE` and `TEST_FOLDERS` constants at the top of the file.  
**Result:** Updates `share_link` and `embed_src` fields in `mapy_data.json` in-place.
