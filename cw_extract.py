"""PDFs/ -> data/cw_pages.jsonl: one record per page of every examiner report, Paper 1/3
question paper and mark scheme, plus the syllabus and learner guide.

Page numbers are the PDF's own (1-based), which is what a reader sees in a viewer and what
the report's citations use. Whitespace is collapsed so quote checks are layout-blind.

ponytail: plain get_text(), no layout model. Quotes that straddle a page break will fail
verification; cite the page the quote starts on and keep quotes inside one page.
"""
import json, re
from pathlib import Path
import pymupdf

ROOT = Path(__file__).resolve().parent
PDFS = ROOT / "PDFs"
OUT = ROOT / "data" / "cw_pages.jsonl"

def kind(name):
    if name.endswith("_er.pdf"): return "er"
    m = re.search(r"_(qp|ms)_\d+\.pdf$", name)
    return m.group(1) if m else "other"

def main():
    OUT.parent.mkdir(exist_ok=True)
    files = sorted(PDFS.glob("Examiner Reports/*.pdf")) + sorted(PDFS.glob("Paper [13]/*.pdf")) \
        + sorted(PDFS.glob("Resources/*.pdf"))
    n = 0
    with OUT.open("w") as f:
        for p in files:
            for i, page in enumerate(pymupdf.open(p)):
                t = re.sub(r"\s+", " ", page.get_text()).strip()
                f.write(json.dumps({"doc": p.stem, "kind": kind(p.name), "page": i + 1, "text": t}) + "\n")
                n += 1
    print(f"{len(files)} files, {n} pages -> {OUT.relative_to(ROOT)}")

if __name__ == "__main__":
    main()
