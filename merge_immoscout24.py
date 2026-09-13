import json

with open("backup_latest.json", "r", encoding="utf-8") as f:
    local_data = json.load(f)
with open("docs/data/latest.json", "r", encoding="utf-8") as f:
    remote_data = json.load(f)

immoscout_rows = [r for r in local_data["listings"] if r.get("Portal") == "ImmoScout24"]
other_rows = [r for r in remote_data["listings"] if r.get("Portal") != "ImmoScout24"]
combined = other_rows + immoscout_rows

remote_data["listings"] = combined
remote_data["count"] = len(combined)
if "ImmoScout24" in local_data.get("sources", {}):
    remote_data.setdefault("sources", {})["ImmoScout24"] = local_data["sources"]["ImmoScout24"]

with open("docs/data/latest.json", "w", encoding="utf-8") as f:
    json.dump(remote_data, f, ensure_ascii=False, indent=2)

print(f"Scalono: {len(other_rows)} nie-ImmoScout24 + {len(immoscout_rows)} ImmoScout24 = {len(combined)} razem.")