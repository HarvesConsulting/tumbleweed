"""Дебаг _title_matches_professions."""
from tumbleweed.services.matcher import _load_subcategories
from tumbleweed.services.text_utils import has_word, normalize

# 1. Завантажити
subs = _load_subcategories("ua")
print(f"Total subs: {len(subs)}")

# 2. Знайти food_cook
sub = subs.get("food_cook")
print(f"food_cook: {sub}")

# 3. Перевірити кожен keyword
if sub:
    for kw in sub.keywords:
        ok = has_word("Кухар", kw)
        print(f"  has_word('Кухар', {kw!r}) = {ok}")

# 4. normalize
print(f"normalize('Кухар') = {normalize('Кухар')!r}")
print(f"normalize('кухар') = {normalize('кухар')!r}")
