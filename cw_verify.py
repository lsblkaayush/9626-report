"""Check every quotation in data/cw_sections/*.json against the source it cites.

A quote passes when, after normalising whitespace, curly quotes and dashes, it is a
substring of the cited document. The page it was found on is written back into the cite
(so citations always carry the real page, whatever the drafter thought). Exits non-zero
and lists every failure if any quote is not found verbatim.

    python3 cw_verify.py            # check all sections
    python3 cw_verify.py Explain    # check one
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SECTIONS = ROOT / "data" / "cw_sections"
SYLLABUS_MD = ROOT / "data" / "syllabus_2025-2027.md"

def norm(s):
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("−", "-").replace("…", "...").replace("•", " ")
    s = s.replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"\s+", " ", s).strip().lower()

def load():
    docs = defaultdict(list)
    for l in open(ROOT / "data" / "cw_pages.jsonl"):
        r = json.loads(l); docs[r["doc"]].append((r["page"], norm(r["text"])))
    return docs

def find(docs, doc, quote):
    q = norm(quote).strip(" .")
    if doc not in docs: return None, "unknown document"
    pages = docs[doc]
    for page, t in pages:
        if q in t: return page, None
    # a quote may cross a page break
    for (p1, t1), (_, t2) in zip(pages, pages[1:]):
        if q in t1 + " " + t2: return p1, None
    return None, "not found verbatim"

def cites_in(obj):
    if isinstance(obj, dict):
        if "doc" in obj and "quote" in obj: yield obj
        for v in obj.values(): yield from cites_in(v)
    elif isinstance(obj, list):
        for v in obj: yield from cites_in(v)

def main(only=None):
    docs = load()
    bad = 0; total = 0
    for f in sorted(SECTIONS.glob("*.json")):
        if only and f.stem != only: continue
        data = json.loads(f.read_text())
        for c in cites_in(data):
            total += 1
            page, err = find(docs, c["doc"], c["quote"])
            if err:
                bad += 1; print(f"FAIL {f.stem}: {c['doc']}: {err}: {c['quote'][:160]!r}")
            else:
                c["page"] = page
        f.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(f"{total - bad}/{total} quotes verified")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
