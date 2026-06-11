#!/usr/bin/env python3
"""
Generate index.html from mapy_data.json using the Jinja2 template.

Usage:
    python generate_site.py
    python generate_site.py --data other_data.json --out output.html
"""
import argparse
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

BASE = Path(__file__).parent
TEMPLATE_DIR = BASE / "templates"
DEFAULT_DATA = BASE / "mapy_data.json"
DEFAULT_OUT  = BASE / "index.html"
FOLDERS_FILE = BASE / "folders.json"

def _icon(f):
    return f'<img src="icons/{f}" class="type-icon-img" alt="">'

TYPE_ICONS = {
    "bike":   _icon("route-cyc-2-icon.png"),
    "hiking": _icon("route-ped-2-icon.png"),
    "car":    _icon("route-car-2-icon.png"),
    "adr":    _icon("route-adr-2-icon.png"),
    "":       _icon("route-adr-2-icon.png"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(DEFAULT_DATA))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"ERROR: data file not found: {data_path}")
        print("  Run scrape_mapy.py first.")
        raise SystemExit(1)

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,  # we escape manually in JS
    )
    template = env.get_template("index.html.j2")

    html = template.render(
        folders=data["folders"],
        icons=TYPE_ICONS,
    )

    out_path = Path(args.out)
    out_path.write_text(html, encoding="utf-8")
    print(f"Generated: {out_path}")

    data_js_path = out_path.parent / "data.js"
    data_js_path.write_text(
        "const DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf-8",
    )
    print(f"Generated: {data_js_path}")

    n_maps = sum(len(f["maps"]) for f in data["folders"])
    print(f"  {len(data['folders'])} folder(s), {n_maps} map(s)")

    if FOLDERS_FILE.exists():
        with open(FOLDERS_FILE, encoding="utf-8") as f:
            folders_raw = json.load(f)
        folders_js_path = out_path.parent / "folders_data.js"
        folders_js_path.write_text(
            "const FOLDERS_DATA = " + json.dumps(folders_raw, ensure_ascii=False, indent=2) + ";\n",
            encoding="utf-8",
        )
        print(f"Generated: {folders_js_path}")


if __name__ == "__main__":
    main()
