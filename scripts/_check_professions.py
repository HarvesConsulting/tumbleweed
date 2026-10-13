"""Перевірка структури professions_ua.json."""
import json
from pathlib import Path

p = Path("data/jobs/professions_ua.json")
d = json.loads(p.read_text(encoding="utf-8"))

cats = d["categories"]
print(f"Категорій: {len(cats)}")
total_subs = 0
for c in cats:
    subs = c.get("subcategories", [])
    total_subs += len(subs)
    print(f"  {c['key']:>8}  {c['label']}  ({len(subs)} підкатегорій)")

print(f"\nВсього підкатегорій: {total_subs}")

# Перевіримо, що всі ключі унікальні
all_keys = [s["key"] for c in cats for s in c.get("subcategories", [])]
dupes = [k for k in set(all_keys) if all_keys.count(k) > 1]
if dupes:
    print(f"⚠️ Дублікати ключів: {dupes}")
else:
    print("✅ Усі ключі унікальні")
