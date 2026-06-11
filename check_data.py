import json
with open("mapy_data.json", encoding="utf-8") as f:
    d = json.load(f)
total = sum(len(fo["maps"]) for fo in d["folders"])
with_embed = sum(1 for fo in d["folders"] for m in fo["maps"] if m.get("embed_src") or m.get("share_link"))
with_points = sum(1 for fo in d["folders"] for m in fo["maps"] if m.get("points"))
print("Folders :", len(d["folders"]))
print("Maps    :", total)
print("With embed/share link:", with_embed)
print("With points          :", with_points)
fo = d["folders"][0]
m = fo["maps"][0]
print("\nSample - TJ Tatry-Gorce 2026 / Turbacz:")
print("  share_link:", repr(m["share_link"]))
print("  embed_src :", repr(m["embed_src"]))
print("  points    :", m["points"][:3])
print("  summary   :", m["summary"])
