"""Assemble Chapterwise Practical/<level>_<slug>/<year>/<Mon_Year>/ from data/practical_plan.json.

Each leaf holds only that chapter's questions (cropped out of the real QP/MS with the
same vector-clip pipeline build_chapterwise_pdfs.py uses) plus only the source files
those questions name.

USAGE: scripts/venv/bin/python3 scripts/build_practical_chapters.py [--from 2020] [--to 2025]
"""
import argparse, json, re, shutil, sys
from collections import defaultdict
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import poc_chapter_pdf as poc
import build_chapterwise_pdfs as bc
import ms_pages
import leaf_pdf

ROOT = Path(__file__).parent.parent
OUT_ROOT = ROOT / "Chapterwise Practical"
MONTH = {"m": ("Mar", "February/March"), "s": ("Jun", "May/June"), "w": ("Nov", "October/November")}
LEVEL = {"as": "AS Level", "a2": "A Level"}
ADMIN = re.compile(r"(practical test|conducting cambridge|9626_)", re.I)


def whole_qnums(qnums):
    """Practical tasks chain over one dataset, so a lettered part on its own is not
    something a candidate could sit. Crop whole questions and drop the duplicates that
    collapsing "3(a)", "3(b)", "3(c)" onto question 3 creates."""
    out = []
    for q in qnums:
        m = re.match(r"\d+[a-z]?", q)
        main = m.group(0) if m else q
        if main not in out:
            out.append(main)
    return out


def marks_for(paper):
    """{qnum: marks}. The bank's own `marks` field is 1 for whole sessions where the
    parse missed the tariff, so trust the "[n]" Cambridge prints at the end of the
    question and keep the stored value only as a fallback."""
    import json as _json
    out = {}
    for x in _json.load(open(ROOT / "data/question_bank.json")):
        if x["paper"] != paper:
            continue
        q, part = x["q"], x["part"]
        part = (part or "").strip("()")
        key = q if part in ("", "None") else f"{q}({part})"
        try:
            stored = int(str(x.get("marks") or 0).strip())
        except ValueError:
            stored = 0
        # a multi-part question prints one "[n]" per part, so the tariff is their sum -
        # checked against all 169 practical rows whose stored value is trustworthy, 0 disagreed
        parts = [int(n) for n in re.findall(r"\[(\d{1,2})\]", x.get("text") or "")]
        value = sum(parts) if parts else stored
        out[key] = value
        # the bank splits some questions into one row per lettered part, but a practical
        # leaf crops the whole question - give the bare number its total too
        if key != q:
            out[q] = out.get(q, 0) + value
    return out


def _check_marks():
    """One runnable check: the bank stores marks=1 for whole sessions it failed to parse,
    and the cover page prints that number. Re-deriving from the printed tariffs must fix
    those without disturbing the rows that were already right."""
    assert marks_for("9626_w23_qp_02")["18"] == 18, "bogus stored marks=1 must be overridden"
    assert marks_for("9626_s24_qp_04")["1"] == 52, "multi-part tariff is the sum of its parts"
    assert marks_for("9626_w23_qp_04")["2"] == 30, "already-correct rows must stay put"
    m = marks_for("9626_m22_qp_04")
    assert m["3"] == 20, f"part-split rows must total onto the bare question, got {m.get('3')}"
    assert m["3(a)"] == 3, "per-part lookups must survive, without doubled brackets"
    print("ok  marks re-derived from printed tariffs, part-split questions totalled")


def paper_dir(paper):
    return ROOT / "PDFs" / ("Paper 2" if paper.endswith(("02", "2", "21")) else "Paper 4")


def build_leaf(g, out, report, also=()):
    """Crop this chapter's questions+answers out of one session's papers into out/."""
    qp = paper_dir(g["paper"]) / f"{g['paper']}.pdf"
    ms = paper_dir(g["paper"]) / f"{g['paper'].replace('_qp_', '_ms_')}.pdf"
    if not qp.exists() or not ms.exists():
        report.append(f"- MISSING PDF {g['paper']} ({g['slug']})")
        return 0, None
    sess = g["session"]
    label = f"9626/{g['paper'].split('_')[-1]} {MONTH[sess[0]][1]} 20{sess[1:]}"

    q_doc, a_doc = pymupdf.open(), pymupdf.open()
    q_flow, a_flow = poc.PageFlow(q_doc), poc.PageFlow(a_doc)
    ok, cropped = 0, []
    qnums = whole_qnums(g["qnums"])
    for qnum in qnums:
        try:
            spans = bc.find_part_crop(qp, qnum, whole=True)
            # the crop coordinates come from the upright copy; draw from the same copy
            src = bc.open_upright(qp)
            # B3-crop-bounds: widened where a picture or a table runs past the 50-545pt
            # margins (9626_w21_qp_04 Q4), as in the Chapterwise PDFs packs
            clips = [(pi, bc.widen_for_cut_text(src[pi], pymupdf.Rect(
                         poc.LEFT_MARGIN, t, poc.RIGHT_MARGIN, b)))
                     for pi, t, b in spans]
            q_flow.place(src, spans[0][0], clips, label, qnum)
            src.close()
            ok += 1
        except Exception as exc:
            report.append(f"- SKIP Q {g['paper']} Q{qnum} ({g['slug']}): {exc}")
        try:
            # find_answer_range decides whether this is a row-per-part mark scheme at all
            # (the pre-2022 screenshot ones are not, and use the page fallback below), but
            # it only returns the rows on one page. A whole practical task takes every row
            # of that task on every page it runs over (ledger P0-PRIOR-015).
            bc.find_answer_range(ms, qnum)
            spans = bc.find_answer_spans(ms, qnum)
            src = bc.open_upright(ms)
            a_flow.place(src, spans[0][0], [(pi, pymupdf.Rect(*bb)) for pi, bb in spans],
                         label, qnum, header_fn=poc.draw_ms_header, split_each_clip=True)
            src.close()
            cropped.append(qnum)
        except Exception:
            pass  # not a row-per-part mark scheme; the page fallback below covers it

    out.mkdir(parents=True, exist_ok=True)
    kw = {"garbage": 4, "deflate": True, "clean": True}
    marks = marks_for(g["paper"])
    year = 2000 + int(sess[1:])
    session_name = f"{MONTH[sess[0]][1]} {year}"
    code = g["paper"].split("_")[-1]
    meta = dict(chapter=g["chapter"], level=LEVEL[g["level"]], paper_code=code,
                session=session_name, qnums=qnums, marks=marks, files=g["files"],
                also=sorted(also))

    # Pre-2022 practical mark schemes are screenshots under loose headings, with no rows
    # to crop. Fall back to whole pages, and to the whole paper when even the headings
    # don't partition it - showing a spare page beats pairing the wrong answer.
    ms_mode, src_pages = "cropped", []
    if len(cropped) == len(qnums) and a_flow.out_doc.page_count:
        ms_doc = a_flow.out_doc
    else:
        src = pymupdf.open(ms)
        pages, ms_mode = ms_pages.resolve(ms, qnums, src.page_count)
        src_pages = pages
        ms_doc = pymupdf.open()
        for pi in pages:
            ms_doc.insert_pdf(src, from_page=pi, to_page=pi)
        src.close()
        report.append(f"- MS fallback ({ms_mode}) {g['paper']} {g['slug']}: pages {[p + 1 for p in pages]}")

    for doc, kind, fname in ((q_flow.out_doc, "QUESTIONS", "QP.pdf"),
                             (ms_doc, "MARK SCHEME", "MS.pdf")):
        if not doc.page_count:
            continue
        # banner the content pages first, then push the cover in front of them
        n = doc.page_count
        for i, page in enumerate(doc, 1):
            right = f"page {i} of {n}"
            # A whole/split mark scheme page is a real CAIE page and still carries
            # Cambridge's own "Page 5 of 13" at the foot. Name that number here too,
            # or the two numberings look like a contradiction.
            if fname == "MS.pdf" and ms_mode != "cropped" and i <= len(src_pages):
                right = f"page {i} of {n}  ·  paper p{src_pages[i - 1] + 1}"
            leaf_pdf.banner(page,
                            left=f"{kind} · 9626/{code} · {session_name} · {g['chapter']}",
                            right=right)
        leaf_pdf.cover(doc, kind=kind, ms_mode=ms_mode, **meta)
        doc.save(out / fname, **kw)

    if ms_doc is not a_flow.out_doc:
        ms_doc.close()
    q_flow.out_doc.close()
    a_flow.out_doc.close()
    return ok, ms_mode, qnums


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", type=int, default=2020)
    ap.add_argument("--to", dest="hi", type=int, default=2025)
    args = ap.parse_args()

    plan = json.load(open(ROOT / "data/practical_plan.json"))
    # which chapters draw on each session, so a leaf can point at a chained file it lacks
    users = defaultdict(lambda: defaultdict(list))
    for g in plan:
        for f in g["files"]:
            users[g["paper"]][f].append(g["slug"])

    # A Paper 4 task is often one integrated problem that examines two chapters at once -
    # w23 Q2 builds a database purely to drive a mail merge. Both chapters legitimately
    # want it, so both get the whole question; say so on the leaf instead of leaving a
    # teacher to wonder why a database folder opens on a mail merge.
    claims = defaultdict(set)
    for g in plan:
        for q in whole_qnums(g["qnums"]):
            claims[(g["paper"], q)].add(g["chapter"])

    if OUT_ROOT.exists():
        shutil.rmtree(OUT_ROOT)
    report, made, modes = ["# Practical chapterwise build report\n"], 0, defaultdict(int)
    for g in plan:
        year = 2000 + int(g["session"][1:])
        if not args.lo <= year <= args.hi:
            continue
        mon = MONTH[g["session"][0]][0]
        out = OUT_ROOT / f"{g['level']}_{g['slug']}" / str(year) / f"{mon}_{year}"
        also = {c for q in whole_qnums(g["qnums"])
                for c in claims[(g["paper"], q)]} - {g["chapter"]}
        ok, ms_mode, qnums = build_leaf(g, out, report, also)
        if not ok:
            continue
        made += 1
        modes[ms_mode] += 1

        sd = Path(g["source_dir"]) if g["source_dir"] else None
        if g["files"] and sd:
            (out / "source").mkdir(exist_ok=True)
            for f in g["files"]:
                shutil.copy2(sd / f, out / "source" / f)

        others = []
        if sd:
            for f in sorted(p.name for p in sd.iterdir() if p.is_file() and not ADMIN.search(p.name)):
                if f not in g["files"]:
                    who = users[g["paper"]].get(f) or ["not referenced by any question"]
                    others.append(f"- `{f}` — used by: {', '.join(sorted(set(who)))}")
        (out / "notes.md").write_text("\n".join([
            f"# {g['chapter']} — {MONTH[g['session'][0]][1]} {year}",
            f"\nPaper: `{g['paper']}.pdf` · Questions in this chapter: {', '.join(qnums)}",
            "\n`QP.pdf` and `MS.pdf` hold only this chapter's questions, cropped from the real paper.",
            ("\n## Shared with other chapters\n\nCambridge set these as one integrated task, so the "
             "same question also appears under:\n\n"
             + "\n".join(f"- {c}" for c in sorted(also))
             + "\n\nThe whole question is kept intact here — parts of it examine those chapters "
               "rather than this one. Paper 4 is allowed to do this: the syllabus says its tasks "
               "come from sections 17–21 and *may also include practical tasks from sections 8–10 "
               "within a problem-solving context*.\n" if also else ""),
            "\n## Source files provided\n",
            "\n".join(f"- `{f}`" for f in g["files"]) or "_None — this chapter's questions create their work from scratch._",
            ("\n_Some of these were opened by an earlier task in this same paper; the questions "
             "here continue on that data._" if g["inherited"] else ""),
            "\n## Other files in this session's archive\n",
            "\n".join(others) or "_None._",
            {"cropped": "\n`MS.pdf` is cropped to this chapter's answers only.",
             "split": "\n`MS.pdf` holds the full mark scheme pages covering this chapter's tasks. "
                      "This session's mark scheme has no per-part rows to crop to.",
             "whole": "\n**`MS.pdf` is this session's complete mark scheme.** Its layout (screenshots "
                      "under loose headings) can't be split by task reliably, so it is kept whole "
                      "rather than risk pairing your question with the wrong answer. "
                      f"Look for tasks {', '.join(qnums)}."}[ms_mode],
            "\nSome practical tasks chain (\"open the file you saved in question 3\"). If a question"
            "\nnames a file that isn't in `source/`, it is listed above with the chapter that has it.\n",
        ]))
    report.insert(1, f"\n**{made} chapter-sessions built ({args.lo}-{args.hi}).**\n")
    (ROOT / "Reports").mkdir(exist_ok=True)
    (ROOT / "Reports/practical_chapterwise_report.md").write_text("\n".join(report))
    print(f"{made} chapter-sessions built -> {OUT_ROOT}")
    print("MS modes:", dict(modes))
    print(f"warnings: {sum(1 for l in report if l.startswith('- '))}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _check_marks()
    else:
        main()
