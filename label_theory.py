"""Add cover pages and page banners to the chapterwise PDFs (Papers 1, 2, 3 and 4).

The Chapterwise Practical leaves got this treatment when they were built; the
build_chapterwise_pdfs.py packs predate it and open straight onto a cropped question with
no statement of what the file is. Runs as a post-process so the 1800-entry chapterwise
build doesn't have to be repeated. Papers 2 and 4 are built by the same script into the
same folders, so they get the same cover and banner (audit finding
F-IT-P2P4-NO-COVER-BANNER: the paper list here used to stop at Papers 1 and 3).

Also surfaces a finding from the tag audit: 2020-2021 theory papers carry a lot of
content the 2022 syllabus revision dropped (input/output devices, storage media,
video-conferencing). Every low-confidence tag in the practice window sits in those two
years. A student should know before spending an evening on it.

USAGE: scripts/venv/bin/python3 scripts/label_theory.py [--cw DIR] ["Paper 1" ...]
       (default: Chapterwise PDFs/, Papers 1 to 4; --cw labels a staging copy instead,
        naming papers labels only those)
"""
import json, re, sys
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import build_chapterwise_pdfs as bc
import leaf_pdf

ROOT = Path(__file__).parent.parent
CW = ROOT / "Chapterwise PDFs"
# paper folder -> (level, paper number). Every paper build_chapterwise_pdfs.py writes a
# pack for must be here, or its packs ship with no cover and no banner.
LEVEL = {"Paper 1": ("AS Level", "1"), "Paper 2": ("AS Level", "2"),
         "Paper 3": ("A Level", "3"), "Paper 4": ("A Level", "4")}
# The 2022 cut removed theory content only; the practical syllabus came through intact
# (README "The paper reports"), so the dropped-content warning is for Papers 1 and 3.
THEORY = {"1", "3"}
DROPPED_NOTE = (
    "Questions from 2020 and 2021 include topics the 2022 syllabus revision removed - "
    "input and output devices, storage media, video-conferencing, RAM vs ROM, and the "
    "internet-vs-web distinction. They are kept because the skill still transfers, but "
    "they are not a guide to what is examined now. Every 2022+ question here maps cleanly "
    "onto the current syllabus.")


def chapter_stats(paper_dir, stem):
    """(entries, marks, {year: n}, low_conf_years) straight from the By Topic source."""
    md = ROOT / "By Topic" / paper_dir / f"{stem}.md"
    entries = bc.parse_chapter_md(md) if md.exists() else []
    years = Counter()
    for e in entries:
        m = re.search(r"(20\d{2})", e["label"])   # not the 9626 in the paper code
        if m:
            years[int(m.group(1))] += 1
    marks = 0
    for line in md.read_text().split("\n") if md.exists() else []:
        m = re.match(r"^\|\s*[^|]+\|[^|]*\|\s*(\d+)\s*\|\s*$", line)
        if m:
            marks += int(m.group(1))
    return entries, marks, years


# The per-item citation poc.draw_item_citation stamps above every placed crop:
# "<label>  •  Question <qnum>[  (continued)]" in 9pt Helvetica ("•" extracts as "·").
CITE_RE = re.compile(r"^(?P<label>\S.*?)\s+[•·∙]\s+Question (?P<q>\S+?)(?P<cont>\s+\(continued\))?$")


def placed_units(doc):
    """{(label, qnum)} of every unit actually printed in this pack, read from its own
    citations (continuations excluded). The By Topic list overstates what a pack holds:
    the builder drops (qp, qnum) duplicates listed under two subtopics and skips entries
    it cannot crop (Reports/chapterwise_build_report.md), and a Questions file can hold
    a unit whose mark-scheme row failed. Audit finding F-IT-COVERCOUNT."""
    units = set()
    for page in doc:
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                spans = ln["spans"]
                if not spans or abs(spans[0]["size"] - 9) > 0.2:
                    continue
                m = CITE_RE.match("".join(sp["text"] for sp in spans).strip())
                if m and not m["cont"]:
                    units.add((m["label"], m["q"]))
    return units


def _n_questions(n):
    return f"{n} question" if n == 1 else f"{n} questions"


def main():
    low_by_id = set()
    for p in ("p1", "p3"):
        for line in open(ROOT / f"data/tagging_manifest_{p}.jsonl"):
            d = json.loads(line)
            if d.get("confidence") == "low":
                low_by_id.add(d["id"])

    args = sys.argv[1:]
    cw = CW
    if "--cw" in args:
        i = args.index("--cw")
        cw = Path(args[i + 1])
        del args[i:i + 2]
    done = 0
    unknown = [a for a in args if a not in LEVEL]
    assert not unknown, f"unknown paper folder(s) {unknown}; expected some of {list(LEVEL)}"
    for paper_dir in [p for p in LEVEL if not args or p in args]:
        level, code = LEVEL[paper_dir]
        for pdf in sorted((cw / paper_dir).glob("*.pdf")):
            stem = pdf.stem
            kind = ("MARK SCHEME" if stem.endswith("- Answers") else
                    "QUESTIONS (WRITE-ON)" if stem.endswith("(write-on)") else "QUESTIONS")
            chapter = stem.rsplit(" - ", 1)[0]
            entries, marks, years = chapter_stats(paper_dir, chapter)
            doc = pymupdf.open(pdf)
            # re-runnable: drop a previous cover and redraw. Banners paint over
            # themselves on an opaque band, so they need no undo.
            if doc[0].get_text().strip().startswith(kind):
                doc.delete_page(0)
            # count what this file prints, not what By Topic lists (F-IT-COVERCOUNT)
            units = placed_units(doc)
            assert units or not entries, f"no item citations found in {pdf}"
            years = Counter()
            for label, _q in units:
                m = re.search(r"(20\d{2})", label)   # not the 9626 in the paper code
                if m:
                    years[int(m.group(1))] += 1
            n = doc.page_count
            for i, page in enumerate(doc, 1):
                leaf_pdf.banner(page,
                                left=f"{kind} · 9626 Paper {code} · {chapter}",
                                right=f"page {i} of {n}")
            # plain hyphen: the base-14 Helvetica on the cover has no en dash and drew the
            # range as "2017·2025"
            span = (("-" if not years else str(min(years)) if min(years) == max(years)
                     else f"{min(years)}-{max(years)}"))
            assert not years or max(years) < 2030, f"bad year parse in {stem}: {sorted(years)}"
            recent = sum(v for k, v in years.items() if k >= 2020)
            cover = leaf_pdf.cover(
                doc, kind=kind, chapter=chapter, level=level, paper_code=code,
                session=f"{span}, all sessions",
                qnums=[_n_questions(len(units))], marks={}, files=None, ms_mode="theory")
            # the cover's task row is a count here, not a task list; add the real detail
            y = 470
            cover.insert_text((56, y), "By year", fontname="hebo", fontsize=9.5,
                              color=leaf_pdf.MUTED)
            # comma-separated: with plain spaces "2017 · 3   2018 · 7" read as "3 2018"
            # wrapped per entry, so a "2024 · 26" pair is never split across two lines
            by_year, ln = [], ""
            for e in (f"{k} · {v}" for k, v in sorted(years.items())):
                trial = f"{ln},   {e}" if ln else e
                if ln and pymupdf.get_text_length(trial + ",", fontname="helv",
                                                  fontsize=10) > 483 - 130:
                    by_year.append(ln + ",")
                    trial = e
                ln = trial
            if ln:
                by_year.append(ln)
            for ln in by_year:
                cover.insert_text((186, y), ln, fontname="helv", fontsize=10,
                                  color=leaf_pdf.INK)
                y += 14
            y += 8
            cover.insert_text((56, y), "Since 2020", fontname="hebo", fontsize=9.5,
                              color=leaf_pdf.MUTED)
            cover.insert_text((186, y), _n_questions(recent), fontname="helv",
                              fontsize=10, color=leaf_pdf.INK)
            y += 30
            if kind == "QUESTIONS (WRITE-ON)":
                note = ("The same questions as the Questions file, in the same order, for "
                        "printing and answering on. Each part keeps the answer space printed "
                        "on the original paper (lines, tables, boxes, flowcharts to complete); "
                        "a part is never split from its space across a page turn unless it "
                        "is longer than a page.")
                for ln in leaf_pdf._wrap(note, 483, 9.5):
                    cover.insert_text((56, y), ln, fontname="helv", fontsize=9.5,
                                      color=leaf_pdf.INK)
                    y += 12.5
                y += 18
            if code in THEORY and any(k <= 2021 for k in years):
                cover.draw_rect(pymupdf.Rect(56, y - 14, 539, y + 52), color=None,
                                fill=(0.99, 0.955, 0.90))
                cover.insert_text((68, y + 3), "Syllabus changed in 2022.",
                                  fontname="hebo", fontsize=10, color=leaf_pdf.WARN)
                yy = y + 19
                for ln in leaf_pdf._wrap(DROPPED_NOTE, 459, 8.5):
                    cover.insert_text((68, yy), ln, fontname="helv", fontsize=8.5,
                                      color=leaf_pdf.INK)
                    yy += 10.5
            # pymupdf refuses a non-incremental save over the open original
            tmp = pdf.with_suffix(".tmp.pdf")
            doc.save(tmp, garbage=4, deflate=True, clean=True)
            doc.close()
            tmp.replace(pdf)
            done += 1
    print(f"labelled {done} chapterwise PDFs")


if __name__ == "__main__":
    main()
