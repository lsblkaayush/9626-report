"""Which pages of a practical mark scheme answer which task.

CAIE changed the practical MS layout around 2022. Newer ones are proper tables with a
row label per part ("1(a)"), which build_chapterwise_pdfs.find_answer_range already
crops. The 2017-2021 ones are free text and screenshots under headings like "Q1.",
"Task 2 - Data dictionary" or "Tasks 1 and 7", with no row structure to crop to.

For those, whole pages are the honest unit: cropping a bbox out of a screenshot-heavy
page drops marks, and pairing the wrong answer with a question is worse than showing
one extra page.

ponytail: heading regex over page text, no layout modelling. If a session slips through
with the wrong pages, add its heading form to HEADING rather than generalising.
"""
import re
from collections import defaultdict

import pymupdf

# "Q1.", "Q1 ", "Task 1", "Tasks 1 and 7", "Task 3 - Charts", "Question 4"
HEADING = re.compile(r"^\s*(?:Q(?:uestion)?|Tasks?)\s*\.?\s*(\d+)\s*(?:and\s*(\d+))?\s*[.–—:\-]?\s*(?:[A-Z(]|$)", re.M)
BOILER = re.compile(r"(GENERIC MARKING PRINCIPLE|Cambridge International AS & A Level|"
                    r"^\s*Page \d+ of \d+|These general marking principles)", re.M | re.I)

_cache: dict[str, dict] = {}


def task_pages(ms_path):
    """{task_number: [page_index, ...]} - a page with no heading of its own continues
    whatever task the previous page was on ("Data Dictionary continued:")."""
    key = str(ms_path)
    if key in _cache:
        return _cache[key]
    doc = pymupdf.open(ms_path)
    pages, current = defaultdict(list), None
    for pi, page in enumerate(doc):
        text = page.get_text()
        # front matter: marking principles, cover page. Never an answer.
        if BOILER.search(text) and not HEADING.search(text):
            if pi < 3:
                current = None
                continue
        found = set()
        for m in HEADING.finditer(text):
            found.update(int(g) for g in m.groups() if g)
        # a table-style MS labels rows "1(a)" with no "Task 1" heading above them
        for m in re.finditer(r"^\s*(\d{1,2})\s*\([a-z]\)", text, re.M):
            found.add(int(m.group(1)))
        if found:
            current = found
        if current:
            for t in current:
                pages[t].append(pi)
    doc.close()
    _cache[key] = dict(pages)
    return _cache[key]


# F-IT-ANSWERS-ROWNOTFOUNDb: the task headings HEADING misses. Used only by the chapterwise
# Answers fallback (build_chapterwise_pdfs.find_answer_pages); task_pages/resolve and so
# Chapterwise Practical are unchanged. HEADING needs a capital, "(" or end of line after the
# number, so it misses a part letter ("Task 6a", "Task 2b – IT in Medicare"), a lower-case
# title ("Task 1 – graphics"), lists and ranges ("Q2, 3 and 4", "Tasks 7, 8 and 9",
# "Tasks 14–16"), and a heading on the line after another ("Task 2\nTask 3": its trailing
# \s* ate the newline and the "T", so the second heading was never seen).
TASK_HEADING = re.compile(
    r"^[ \t]*(?:Q(?:uestion)?|Tasks?)\s*\.?[ \t]*(\d+)[ \t]*(?:[a-z]\b|\([a-z]+\))?"
    r"([ \t]*[–—-][ \t]*\d+\b(?![ \t]*marks?\b)|(?:[ \t]*,[ \t]*\d+)*(?:[ \t]*(?:and|&)[ \t]*\d+)?)", re.M)
_HEAD_WORDS = re.compile(r"^(question|answer|marks?|guidance|\d+)$", re.I)

_full_cache: dict[str, dict] = {}


def _heading_numbers(m):
    first = int(m.group(1))
    rest = [int(x) for x in re.findall(r"\d+", m.group(2) or "")]
    if rest and re.match(r"[ \t]*[–—-]", m.group(2)) and first < rest[0] <= first + 20:
        return set(range(first, rest[0] + 1))
    return {first, *rest}


def task_pages_full(ms_path):
    """{task_number: [page_index, ...]} like task_pages, with TASK_HEADING, and a page that
    starts with the tail of the previous task above its first heading also counts for that
    previous task (an answer that runs onto the top of the next task's page). Front matter
    is skipped the same way as task_pages."""
    key = str(ms_path)
    if key in _full_cache:
        return _full_cache[key]
    doc = pymupdf.open(ms_path)
    pages, current = defaultdict(set), None
    for pi, page in enumerate(doc):
        text = page.get_text()
        if BOILER.search(text) and not HEADING.search(text) and not TASK_HEADING.search(text):
            if pi < 3:
                current = None
                continue
        found, first_y = set(), None
        # F-IT-ANSWERS-ROWNOTFOUNDb (round 2): line y in the DISPLAYED frame. On a
        # /Rotate 90 page (9626_s21_ms_02, w20_ms_02, w21_ms_02) PyMuPDF gives bboxes in
        # the unrotated frame, where y runs across the landscape page; the "tail above
        # the first heading" rule below then fired on every page and gave each task the
        # next task's page. rotation_matrix maps to the frame page.rect (and the build's
        # open_upright) uses; for an unrotated page it is the identity.
        rot_m = page.rotation_matrix
        lines = []
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                t = "".join(s["text"] for s in ln["spans"]).strip()
                if t:
                    lines.append(((pymupdf.Rect(ln["bbox"]) * rot_m).y0, t))
        lines.sort()
        for y, t in lines:
            hit = [m for m in TASK_HEADING.finditer(t)] + \
                  [m for m in re.finditer(r"^\s*(\d{1,2})\s*\([a-z]\)", t)]
            if not hit:
                continue
            for m in hit:
                found |= _heading_numbers(m) if m.re is TASK_HEADING else {int(m.group(1))}
            first_y = y if first_y is None else min(first_y, y)
        # the text-order scan as well, so nothing HEADING/task_pages sees is lost
        for m in TASK_HEADING.finditer(text):
            found |= _heading_numbers(m)
        for m in re.finditer(r"^\s*(\d{1,2})\s*\([a-z]\)", text, re.M):
            found.add(int(m.group(1)))
        for m in HEADING.finditer(text):
            found.update(int(g) for g in m.groups() if g)
        if found and current and first_y is not None:
            ph = page.rect.height
            above = [t for y, t in lines if 46 <= y < first_y - 2 and y < ph - 60
                     and not BOILER.search(t) and not _HEAD_WORDS.match(t)
                     and "dynamicpapers" not in t.lower()]
            if above:                      # tail of the previous task above the heading
                for t in current:
                    pages[t].add(pi)
        if found:
            current = found
        if current:
            for t in current:
                pages[t].add(pi)
    doc.close()
    _full_cache[key] = {t: sorted(ps) for t, ps in pages.items()}
    return _full_cache[key]


def resolve(ms_path, qnums, page_count):
    """(pages, mode) - which MS pages to ship for these tasks.

    "split" when the headings genuinely partition the paper; "whole" when they don't,
    in which case every content page is shipped and the caller should say so. A task
    map that hands most of the paper to one task is not a partition, it is a miss.
    """
    tp = task_pages(ms_path)
    front = 2 if page_count > 4 else 0     # cover + generic marking principles
    content = [i for i in range(front, page_count)]
    wanted = {int(re.match(r"\d+", q).group()) for q in qnums if re.match(r"\d+", q)}
    hit = sorted({p for t in wanted for p in tp.get(t, []) if p >= front})
    if len(tp) < 2 or not hit or len(hit) > 0.6 * max(len(content), 1):
        return content, "whole"
    return hit, "split"


def demo():
    """One runnable check: the two layout eras must both resolve task 1 to real pages."""
    import sys
    from pathlib import Path
    root = Path(__file__).parent.parent
    for f, era in [("PDFs/Paper 2/9626_s24_ms_02.pdf", "table"),
                   ("PDFs/Paper 2/9626_s21_ms_02.pdf", "free text"),
                   ("PDFs/Paper 2/9626_m20_ms_02.pdf", "free text")]:
        tp = task_pages(root / f)
        assert tp, f"{f}: no tasks found at all"
        assert 1 in tp, f"{f}: task 1 missing, got tasks {sorted(tp)}"
        assert all(p >= 1 for p in tp[1]), f"{f}: task 1 landed on the cover page"
        print(f"ok  {era:10} {Path(f).name}: " +
              ", ".join(f"T{t}->p{[p+1 for p in ps]}" for t, ps in sorted(tp.items())[:6]))

    # a real partition splits; a paper with no usable headings must fall back, not lie
    n = pymupdf.open(root / "PDFs/Paper 2/9626_s24_ms_02.pdf").page_count
    pages, mode = resolve(root / "PDFs/Paper 2/9626_s24_ms_02.pdf", ["1"], n)
    assert mode == "split", f"s24 should split, got {mode}"
    n = pymupdf.open(root / "PDFs/Paper 2/9626_m20_ms_02.pdf").page_count
    pages, mode = resolve(root / "PDFs/Paper 2/9626_m20_ms_02.pdf", ["1"], n)
    assert mode == "whole", f"m20 has no task headings, should fall back, got {mode}"
    assert 0 not in pages and 1 not in pages, "front matter must be dropped"
    print("demo passed")


if __name__ == "__main__":
    demo()
