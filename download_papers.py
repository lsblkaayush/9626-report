"""Fetch 9626 qp+ms PDFs from dynamicpapers into PDFs/. Skips 404s and files already present.

ponytail: flat URL pattern + HEAD-less GET, no retry/backoff logic. Add retries if the
host starts rate-limiting.
"""
import sys, urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

SOURCES = [
    lambda n: "https://dynamicpapers.com/wp-content/uploads/2015/09/" + n,
    lambda n: f"https://papers.gceguide.cc/a-levels/information-technology-9626/20{n[6:8]}/{n}",
]
OUT = Path("PDFs")
# The practicals are served under several spellings of the same file: 9626_m17_qp_22,
# 9626_m17_qp_02 and 9626_m21_ms_2 are all one paper. The vault keeps the _02 / _04
# form throughout, so only fetch that one. Adding the others back gives you 85 duplicate
# PDFs and a question bank that counts several sittings twice.
PAPERS = {
    "1": ["11", "12", "13"],
    "2": ["02"],
    "3": ["31", "32", "33"],
    "4": ["04"],
}


def jobs(which):
    # "er" is the examiner report and "gt" the grade thresholds: one per session each,
    # so neither takes a paper or variant suffix.
    if which in ("er", "gt"):
        for s in "msw":
            for yy in range(17, 27):
                yield f"9626_{s}{yy}_{which}.pdf"
        return
    for s in "msw":
        for yy in range(17, 27):
            for v in PAPERS[which]:
                for kind in ("qp", "ms"):
                    yield f"9626_{s}{yy}_{kind}_{v}.pdf"


def subdir(name):
    """PDFs/Paper 3/ for a question paper or mark scheme, and a folder of its own for
    the two per-session documents. The variant's leading digit is the paper number,
    except on the practicals, which dropped the variant digit in 2019 and left the
    paper number in the second position: 02 is Paper 2, 04 is Paper 4."""
    tail = name.rsplit("_", 1)[-1].removesuffix(".pdf")
    if tail in ("er", "gt"):
        return {"er": "Examiner Reports", "gt": "Grade Thresholds"}[tail]
    return "Paper " + (tail[1] if tail[0] == "0" else tail[0])


def get(name):
    dest = OUT / subdir(name) / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return None
    for url_of in SOURCES:
        try:
            req = urllib.request.Request(url_of(name), headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
        except Exception:
            continue
        if data.startswith(b"%PDF"):
            dest.write_bytes(data)
            return name
    return None


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    names = [n for w in sys.argv[1:] for n in jobs(w)]
    with ThreadPoolExecutor(8) as ex:
        got = [r for r in ex.map(get, names) if r]
    print(f"downloaded {len(got)} / tried {len(names)}")
