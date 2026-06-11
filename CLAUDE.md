# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project automates or scrapes [mapy.com](https://mapy.com) — a Central European mapping service. The goal appears to be interacting with the "Moje Mapy" (My Maps) section: reading map folders, routes, and exporting/importing GPX files.

Reference map: https://mapy.com/s/jamofadave  
Main target page: https://mapy.com/en/turisticka?moje-mapy&cat=mista-trasy

## Key Data Files

- `export.gpx` — GPX export of one or more routes (large, ~420KB); serves as sample input/output data.
- `plan.txt` — HTML structure notes extracted from mapy.com, documenting the DOM selectors needed for scraping.

## mapy.com DOM Structure (from plan.txt)

These selectors describe the "Moje Mapy" page structure:

| Element | Selector |
|---|---|
| Map folders list | `ul.folders.sortable` |
| Single folder | `li.folder.public` |
| Folder name | `div.bar > h2.title.overflow-ellipsis` |
| Folder actions menu | `span.opts` |
| Maps list inside folder | `ul.items.sortable` |
| Single map | `li.item.public` |
| Map name + description | `div.text-cover > div > h2.title.overflow-ellipsis` (name), `h3.desc.overflow-ellipsis` (e.g. "Route 14.3 km • 5:00 h") |
| Map actions menu | `span.opts` |
| Opened context menu | `div.ui-popover.ui-contextmenu.ui-popover--bottom-end` |
| Context menu item button | `button.ui-contextmenuitem` |

## No Build System Yet

There is no code, dependency file, or build system in this repo. When adding code, choose tooling appropriate to the task (e.g. Python with `playwright` or `selenium` for browser automation, or `requests`+`BeautifulSoup` for simpler scraping).
