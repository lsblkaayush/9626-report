"""Unnest SourceFiles/raw/*.zip into SourceFiles/extracted/<session_code>/.

CAIE ships a zip containing another zip ("...Confidential source files...") plus an
admin .docx. Recurse until no zips are left, drop the SRF admin form, flatten the
directory noise so a lookup by bare filename works.

ponytail: recursion depth is unbounded but real archives nest twice at most.
"""
import re, shutil, zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
RAW = ROOT / "SourceFiles/raw"
OUT = ROOT / "SourceFiles/extracted"
JUNK = re.compile(r"(SRF|Electronic SRF|__MACOSX|\.DS_Store|Thumbs\.db)", re.I)


def unpack(zpath, dest):
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            if info.is_dir() or JUNK.search(info.filename):
                continue
            name = Path(info.filename).name
            if not name:
                continue
            target = dest / name
            # a nested zip is a container, not content: recurse into it
            if name.lower().endswith(".zip"):
                tmp = dest / ("_nested_" + name)
                tmp.write_bytes(z.read(info))
                unpack(tmp, dest)
                tmp.unlink()
                continue
            if target.exists():           # same basename twice: keep both
                target = dest / f"{target.stem}__dup{target.suffix}"
            target.write_bytes(z.read(info))


if __name__ == "__main__":
    if OUT.exists():
        shutil.rmtree(OUT)
    for z in sorted(RAW.glob("*.zip")):
        code = z.stem                     # 9626_s24_sf_02
        dest = OUT / code
        dest.mkdir(parents=True)
        try:
            unpack(z, dest)
        except zipfile.BadZipFile:
            print(f"  BAD ZIP {code}")
            continue
        files = sorted(p.name for p in dest.iterdir())
        print(f"{code}: {len(files)} files -> {', '.join(files[:8])}{' ...' if len(files) > 8 else ''}")
