"""Fetch official 9626 practical source-file zips from dynamicpapers into SourceFiles/raw/.

ponytail: the sf zips are a zip-inside-a-zip; unnesting happens in extract, not here.
"""
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

# Neither mirror is complete: dynamicpapers is missing the March sessions and June 2020,
# papacambridge is missing Oct/Nov 2020 and March 2024. Together they cover 2020-2025.
# Note the source zips use _02/_04 even for years whose question papers use _21/_41.
SOURCES = [
    "https://dynamicpapers.com/wp-content/uploads/2015/09/{}",
    "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/{}",
]
OUT = Path("SourceFiles/raw")
# 2022+ sessions use _02/_04; earlier ones use the variant digit _21/_41.
NAMES = [f"9626_{s}{yy}_sf_{v}.zip"
         for s in "msw" for yy in range(17, 26) for v in ("02", "04", "21", "41")]


def get(name):
    dest = OUT / name
    if dest.exists():
        return name
    for url in SOURCES:
        try:
            req = urllib.request.Request(url.format(name), headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=300).read()
        except Exception:
            continue
        # papacambridge serves a soft-200 HTML page for misses, so check the magic bytes
        if data.startswith(b"PK"):
            dest.write_bytes(data)
            return name
    return None


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(8) as ex:
        got = [r for r in ex.map(get, NAMES) if r]
    print(f"got {len(got)} / tried {len(NAMES)}")
    for g in sorted(got):
        print(" ", g)
