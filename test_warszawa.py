"""Тест: чи працює warszawa."""
import asyncio
from tumbleweed.parsers.olx_jobs import OLX_COUNTRIES, OlxJobParser


async def main() -> None:
    p = OlxJobParser(OLX_COUNTRIES["pl"])
    r = await p.fetch(city_slug="warszawa", query="kierowca", limit=10)
    print(f"\nFound: {len(r)}")
    for v in r[:5]:
        print(f"  {v.title[:70]}")


if __name__ == "__main__":
    asyncio.run(main())
