"""Перевірка завантаження PL міст."""
from tumbleweed.parsers.olx_jobs import OLX_COUNTRIES

pl = OLX_COUNTRIES["pl"]
print(f"PL cities loaded: {len(pl.city_ids)}")

# Покажи кілька прикладів
for slug in ["warszawa", "gdansk", "krakow", "wroclaw", "poznan"]:
    city_id = pl.city_ids.get(slug, "❌ NOT FOUND")
    print(f"  {slug:12s} → {city_id}")
