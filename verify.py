"""
Health check for the vault. Run after any rebuild.

    python3 scripts/verify.py

Checks folder layout, tagging coverage, and that the generated topic files are
well-formed Markdown tables with no extraction junk left in them. Exits non-zero
if anything is wrong, so it can gate a rebuild.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

JUNK_PATTERNS = [
    (r"www\.dynamicpapers", "DynamicPapers watermark"),
    (r"©\s*UCLES", "UCLES copyright footer"),
    (r"9626/\d{2}/[A-Z]", "paper code footer"),
    (r"\.{6,}", "dot leaders"),
    (r"DO NOT WRITE IN THIS MARGIN", "margin text"),
    (r"[ĬĥÕõÅµą]{4,}", "anti-piracy watermark mojibake"),
    (r"\[Turn over", "'Turn over' footer"),
    (r"\*\*\[\d+\]\*\*", "stray mark marker in cell"),
    (r"BLANK PAGE", "blank page marker"),
]


def main():
    fails, warns = [], []

    # --- root hygiene -------------------------------------------------------
    stray = [p.name for p in ROOT.iterdir()
             if p.is_file() and p.suffix.lower() not in {".md", ".pdf", ".html"}]
    if stray:
        fails.append(f"non-md/pdf/html files in root: {stray}")

    # --- papers sorted ------------------------------------------------------
    for base in ("PDFs", "Text"):
        loose = [p.name for p in (ROOT / base).glob("*.pdf")] + \
                [p.name for p in (ROOT / base).glob("*.md")]
        if loose:
            fails.append(f"{base}/ has {len(loose)} unsorted files at top level")
    counts = {b: {d.name: len(list(d.glob('*'))) for d in sorted((ROOT / b).glob("Paper *"))}
              for b in ("PDFs", "Text")}
    print("papers by folder:")
    for b, c in counts.items():
        print(f"  {b}: {c}")

    # --- image links --------------------------------------------------------
    broken = 0
    total = 0
    for f in list((ROOT / "Text").rglob("Paper */*.md")) + list((ROOT / "By Topic").rglob("*.md")):
        for m in re.finditer(r"\]\(([^)]*images/[^)]*)\)", f.read_text(errors="replace")):
            total += 1
            if not (f.parent / m.group(1)).exists():
                broken += 1
    print(f"image links: {total} total, {broken} broken")
    if broken:
        fails.append(f"{broken} broken image links")

    # --- tagging coverage ---------------------------------------------------
    bank = json.loads((DATA / "question_bank.json").read_text())
    taggable = {f"{u['paper']}:{u['q']}{u['part'] or ''}"
                for u in bank if "dupe_of" not in u}
    taxonomy = json.loads((DATA / "taxonomy.json").read_text())
    valid = {s for t in taxonomy.values() for s in t["subtopics"]}
    tagged, conf, bad_topics = set(), Counter(), []
    for f in DATA.glob("tagging_manifest_*.jsonl"):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            tagged.add(e["id"])
            conf[e.get("confidence", "?")] += 1
            bad_topics += [t for t in e["topics"] if t not in valid]
    missing = taggable - tagged
    print(f"tagging: {len(tagged & taggable)}/{len(taggable)} taggable units, "
          f"confidence {dict(conf)}")
    if missing:
        fails.append(f"{len(missing)} units untagged (e.g. {sorted(missing)[:3]})")
    if bad_topics:
        fails.append(f"{len(bad_topics)} tags use subtopics not in the taxonomy")

    # --- generated topic files ---------------------------------------------
    junk = Counter()
    badrows = []
    entries = 0
    for f in (ROOT / "By Topic").rglob("*.md"):
        txt = f.read_text(errors="replace")
        entries += txt.count("\n#### P ")
        for pat, name in JUNK_PATTERNS:
            n = len(re.findall(pat, txt))
            if n:
                junk[name] += n
        for i, line in enumerate(txt.split("\n"), 1):
            if line.startswith("|") and len(re.findall(r"(?<!\\)\|", line)) != 4:
                badrows.append(f"{f.name}:{i}")
    print(f"topic files: {len(list((ROOT/'By Topic').rglob('*.md')))}, entries: {entries}")
    if badrows:
        fails.append(f"{len(badrows)} malformed table rows (e.g. {badrows[:3]})")
    if junk:
        warns.append(f"extraction junk still present: {dict(junk)}")

    # --- report -------------------------------------------------------------
    print()
    for w in warns:
        print(f"WARN  {w}")
    for f_ in fails:
        print(f"FAIL  {f_}")
    if not fails and not warns:
        print("all checks passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
