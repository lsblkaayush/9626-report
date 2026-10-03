"""Frankenstein AS mock papers: stitch hand-picked questions from several sessions
into one QP.pdf + MS.pdf + source/ per mock.

Why hand-picked and not generated: practical tasks chain ("the file you saved in
step 15"), so a block is only safe to lift if it either stands alone or carries its
own head. MOCKS below is that judgement, written down.

USAGE: scripts/venv/bin/python3 scripts/build_mock_papers.py [--check]
"""
import argparse, json, re, shutil, sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import poc_chapter_pdf as poc
import build_chapterwise_pdfs as bc
import build_practical_chapters as bpc
import leaf_pdf

ROOT = Path(__file__).parent.parent
OUT_ROOT = ROOT / "Mock Papers" / "AS"
DURATION = "3 hours 30 minutes"
SESS_NAME = {"m": "February/March", "s": "May/June", "w": "October/November"}
SF = {"m17": "9626_m17_sf_21", "s17": "9626_s17_sf_21", "w17": "9626_w17_sf_21",
      "s18": "9626_s18_sf_21", "s19": "9626_s19_sf_21", "w19": "9626_w19_sf_21"}

# Files a question needs but never names in words the scanner can match
# ("the Turtleweek logo", "in your TTSMerge file", "the Evidence Document provided").
EXTRAS = {
    ("m17", "2"): ["173Logo1.png"],
    ("s17", "1"): ["TTSMerge.csv", "Branch_Analysis.csv", "Evidence.rtf"],
    ("w17", "1"): ["Evidence.rtf"],
    ("w17", "7"): ["Evidence.rtf", "SoundClip1.mp3"],
    ("s18", "1"): ["186title.csv"],
    ("w19", "8"): ["Employees.txt"],
}

# find_part_crop locates a question's heading but not always its true extent. Two ways
# it goes wrong, both measured once against the source PDF and written down here as
# (top, bottom); None on either side keeps whatever the detector returned.
#   - it stops at the top of a figure that belongs to the question, cutting the figure
#     and the tariff printed under it (s19 Q4 lost its diagram and its [5]);
#   - it runs past the end of the question into whatever Cambridge printed next, which
#     for a question sitting just above a scenario means dragging that scenario in.
CROP = {
    ("9626_s19_qp_02", "4"): (None, 794),  # title-text figure + "[5]" sit below the cut
    ("9626_w19_qp_02", "6"): (348, 455),   # detector opens inside Q5's export task
    ("9626_w19_qp_02", "7"): (None, 372),  # detector runs on into the Ellmau scenario
}


# Mock A carries February/March 2017 Q15-Q18 AND May/June 2019 Q15-Q18, so a question's
# own "step 15" is ambiguous on the page - it could be Task 2 or Task 9. The wording is
# a cropped image and cannot be edited, so the resolution gets printed under the task.
# Keyed (paper, qnum) -> list of (phrase as printed, original qnums it means).
GLOSS = {
    ("9626_m17_qp_02", "17"): [("questions 15 and 16", ["15", "16"])],
    ("9626_s19_qp_02", "16"): [("step 15", ["15"])],
    ("9626_s19_qp_02", "17"): [("step 16", ["16"])],
}


def gloss_for(paper, qnum, task_of):
    """"step 15" -> "In this paper, 'step 15' is Task 9." Silent if the referenced
    question is not in this mock - the selection rules already forbid that case, and a
    wrong gloss would be worse than none."""
    out = []
    for phrase, refs in GLOSS.get((paper, qnum), []):
        tasks = [task_of.get((paper, r)) for r in refs]
        if all(tasks):
            named = " and ".join(f"Task {t}" for t in tasks)
            out.append(f"In this paper, \u201c{phrase}\u201d means {named}.")
    return "  ".join(out)


def crop_spans(qp, paper, qnum):
    """find_part_crop's answer with any measured override from CROP applied."""
    spans = bc.find_part_crop(qp, qnum, whole=True, preamble=False)
    ov = CROP.get((paper, qnum))
    if ov:
        pi, top, bot = spans[-1]
        spans[-1] = (pi, top if ov[0] is None else ov[0], bot if ov[1] is None else ov[1])
    return spans

# ms: 1-based page numbers of the session mark scheme that answer this block.
# Pre-2020 practical mark schemes are screenshots under loose headings with no
# per-question rows to cut to, so pages are the finest honest grain. Read once,
# written down here.
MOCKS = {
    "Mock A": dict(
        subtitle="Auction pivot tables · Ellmau staff database · Ellmau promo video",
        blocks=[
            dict(paper="9626_m17_qp_02", topic="8 Spreadsheets",
                 qnums=["14", "15", "16", "17", "18", "19", "20"],
                 pre="The last fundraising event",
                 # m17 prints this scheme twice: per-question rows on pp3-4, then the
                 # same marks restated by artefact on pp7-13. Carrying both offered 103
                 # criteria for 40 marks and invited double-counting. Rows only.
                 ms=[3, 4]),
            dict(paper="9626_m17_qp_02", topic="8 Spreadsheets — charting",
                 qnums=["23"], ms=[4, 16]),
            dict(paper="9626_s19_qp_02", topic="10 Database and file concepts",
                 qnums=["15", "16", "17", "18"], pre="Employees in Ellmau",
                 ms=[4, 5, 7, 8, 9]),
            dict(paper="9626_w19_qp_02", topic="10 Databases — normalisation",
                 qnums=["6"], ms=[4]),
            dict(paper="9626_s19_qp_02", topic="11 Video editing",
                 qnums=["1", "2", "3", "4", "8"], pre=True, ms=[3]),
            dict(paper="9626_s19_qp_02", topic="11 Audio editing",
                 qnums=["9", "10", "11"], ms=[4]),
        ]),
    "Mock B": dict(
        subtitle="Encrypted bank transactions · Factory staff database · Turtleweek video",
        blocks=[
            dict(paper="9626_s18_qp_02", topic="8 Spreadsheets",
                 qnums=["1", "2", "3", "4", "5", "7"], pre=True,
                 ms=[4, 5, 6, 7, 9, 10]),
            dict(paper="9626_w17_qp_02", topic="10 Database and file concepts",
                 qnums=["1", "2", "3", "4"], pre=True, ms=[2, 3, 4, 5]),
            dict(paper="9626_w19_qp_02", topic="10 Databases — queries",
                 qnums=["7"], ms=[4]),
            dict(paper="9626_m17_qp_02", topic="11 Video editing",
                 qnums=["1", "2", "3", "7"], pre=True, ms=[2, 5]),
        ]),
    "Mock C": dict(
        subtitle="TTS payroll and pay scales · Ellmau employee register · Ski school video",
        blocks=[
            dict(paper="9626_s17_qp_02", topic="8 Spreadsheets",
                 qnums=["1"], pre=True, ms=[2, 3, 4, 5, 6]),
            dict(paper="9626_w19_qp_02", topic="10 Database and file concepts",
                 qnums=["8", "10"], pre="Employees in Ellmau", ms=[4, 5, 8]),
            dict(paper="9626_w19_qp_02", topic="11 Video editing",
                 qnums=["1", "2", "5"], pre=True, ms=[3]),
            dict(paper="9626_m17_qp_02", topic="11 Audio editing",
                 qnums=["8", "9", "10"], ms=[2, 3, 6]),
            dict(paper="9626_w17_qp_02", topic="11 Audio file formats",
                 qnums=["7"], ms=[7]),
        ]),
}

INK, MUTED, RULE, ACCENT = leaf_pdf.INK, leaf_pdf.MUTED, leaf_pdf.RULE, leaf_pdf.ACCENT


def sess_of(paper):
    return paper.split("_")[1]


def sess_label(sess):
    return f"9626/02 {SESS_NAME[sess[0]]} 20{sess[1:]}"


def label_of(paper):
    return sess_label(sess_of(paper))


def qtext(paper, qnum):
    """The question's own wording, from the already-extracted paper text. Stops at the
    answer: the extract appends the whole mark scheme after the last question, and that
    names every file in the archive - including the other tasks'."""
    md = (ROOT / "Text/Paper 2" / f"{paper}.md").read_text()
    m = re.search(rf"^## Question {qnum} —.*?$(.*?)(?=^## Question |^### Mark scheme|^## Full mark|\Z)",
                  md, re.S | re.M)
    return m.group(1) if m else ""


def files_for(paper, qnums):
    """Only the source files these questions actually name, so a mock's source/ isn't a
    dump of three whole archives with other mocks' data sitting in it."""
    sess = sess_of(paper)
    avail = sorted(p.name for p in (ROOT / "SourceFiles/extracted" / SF[sess]).iterdir()
                   if p.is_file())
    out = []
    for q in qnums:
        body = qtext(paper, q).lower()
        for f in avail:
            if f.lower() in body and f not in out:
                out.append(f)
        for f in EXTRAS.get((sess, q), []):
            if f not in out:
                out.append(f)
    return out


RUNNING = re.compile(r"^(\s*\d+\s*$|9626/02|©\s*UCLES|www\.|\[Turn over|BLANK PAGE)")


def preamble_span(qp, qnum):
    """The scenario + rubric Cambridge prints above a question and marks you against
    ("single portrait page ... 12 points high", "field names ... no spaces"). It is not
    part of any question, so cropping questions alone silently drops it and the candidate
    loses marks for an instruction they were never given.

    Returns (page_index, top, bottom) of the gap between the previous question and this
    one, or None when there is nothing in it."""
    pi, top, _ = bc.find_part_crop(qp, qnum, whole=True, preamble=False)[0]
    start = None
    if int(qnum) > 1:
        try:
            for p_, _t, b in bc.find_part_crop(qp, str(int(qnum) - 1), whole=True, preamble=False):
                if p_ == pi:
                    start = b
        except Exception:
            pass
    if start is None:
        doc = pymupdf.open(qp)
        ys = [b[1] for b in doc[pi].get_text("blocks")
              if b[4].strip() and not RUNNING.match(b[4].strip())]
        doc.close()
        start = min(ys) - 4 if ys else 0
    return (pi, start, top) if top - start > 24 else None


def preamble_from(qp, qnum, opening):
    """Mid-paper rubric: the gap-hunt above cannot see it, because Cambridge prints it
    after the previous question's tariff and inside that question's crop. Anchor on its
    first words instead."""
    pi, top, _ = bc.find_part_crop(qp, qnum, whole=True, preamble=False)[0]
    doc = pymupdf.open(qp)
    ys = [b[1] for b in doc[pi].get_text("blocks") if b[4].strip().startswith(opening)]
    doc.close()
    if not ys:
        raise ValueError(f"preamble {opening!r} not found on page {pi + 1} of {qp.name}")
    return pi, min(ys) - 4, top


# PyMuPDF writes these pages in base-14 Helvetica, whose WinAnsi encoding silently
# turns anything it cannot map into a stray dot - smart quotes and dashes came out as
# middle dots on the first build. Spell them the way the font can actually print.
FLATTEN = {"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
           "\u2014": " - ", "\u2013": "-", "\u2022": "-", "\u00b7": "-"}


def flat(s):
    for a, b in FLATTEN.items():
        s = s.replace(a, b)
    return s


class Sheet:
    """A y-cursor over as many A4 pages as the content needs. The front matter plus a
    20-row task map does not fit on one page, and silently running off the bottom is
    how a paper loses its last four tasks."""

    def __init__(self, doc, at=0):
        self.doc, self.at, self.pages = doc, at, []
        self._new()

    def _new(self):
        self.page = self.doc.new_page(self.at + len(self.pages), width=595, height=842)
        self.pages.append(self.page)
        self.y = 86

    def room(self, h):
        if self.y + h > 790:
            self._new()

    def text(self, s, *, size=9.5, font="helv", color=INK, x=56, gap=None, width=483):
        for ln in leaf_pdf._wrap(flat(s), width, size, font):
            self.room(size + 4)
            self.page.insert_text((x, self.y), ln, fontname=font, fontsize=size, color=color)
            self.y += (gap or size + 3.5)

    def rule(self, pad=8, w=0.8):
        self.room(pad + 2)
        self.page.draw_line((56, self.y), (539, self.y), color=RULE, width=w)
        self.y += pad


def front_matter(sh, *, name, subtitle, total, files, renamed):
    """Cambridge's own page 1, in Cambridge's own order: what the paper is, how long you
    get, what you are given, INSTRUCTIONS, INFORMATION. Students who have sat a real
    9626/02 should recognise the page before they read a word of it."""
    sh.text("INFORMATION TECHNOLOGY", size=13, font="hebo")
    sh.y += 4
    sh.text("Paper 2  Practical", size=13, font="hebo")
    sh.page.insert_text((440, sh.y - 21), "9626/02", fontname="hebo", fontsize=13, color=INK)
    sh.page.insert_text((440, sh.y - 4), DURATION, fontname="helv", fontsize=11, color=INK)
    sh.y += 10
    sh.text(f"AS Practical {name} — {subtitle}", size=10, color=MUTED)
    sh.y += 8
    sh.text("You will need:  the candidate source files listed below.", size=10)
    sh.y += 6
    sh.rule()
    sh.y += 10

    sh.text("INSTRUCTIONS", size=10, font="hebo")
    sh.y += 4
    for b in ("Carry out every instruction in each task.",
              "Save your work using the file names given in the task as and when instructed.",
              "You must not have access to either the internet or any email system during "
              "this examination.",
              "You must save your work in the correct file format as stated in the tasks. If "
              "work is saved in an incorrect file format, you will not receive marks for that "
              "task.",
              "Work through the tasks in the order they are printed. A task may use a file you "
              "saved in an earlier task.",
              "Keep ONE Evidence Document for the whole paper unless a task names a specific "
              "file to open. Tasks are reprinted from several papers, so more than one of them "
              "tells you to create an Evidence Document and the numbered Evidence labels inside "
              "them restart; create it the first time you are asked and add to that same "
              "document every time a task says \u201cyour Evidence Document\u201d."):
        sh.room(13)
        sh.page.draw_circle((65, sh.y - 3), 1.9, color=None, fill=INK)
        sh.text(b, x=76, width=463)
        sh.y += 3
    sh.y += 10

    sh.text("INFORMATION", size=10, font="hebo")
    sh.y += 4
    for b in (f"The total mark for this paper is {total}.",
              "The number of marks for each task is shown in brackets [ ].",
              "Tasks are numbered in the grey band above each one. The number printed "
              "inside a task is its number in the original Cambridge paper; where a task "
              "says \u201cstep n\u201d or \u201cquestion n\u201d it means that original number, and the "
              "task list overleaf maps the two.",
              "Any businesses described in this paper are entirely fictitious."):
        sh.room(13)
        sh.page.draw_circle((65, sh.y - 3), 1.9, color=None, fill=INK)
        sh.text(b, x=76, width=463)
        sh.y += 3
    sh.y += 12

    sh.text("CANDIDATE SOURCE FILES", size=10, font="hebo")
    sh.y += 4
    for f in files:
        sh.text(f, size=9.5, x=76)
    sh.y += 6
    if renamed:
        sh.text("Two of the sessions this paper draws on each ship an Evidence Document called "
                "Evidence.rtf. Both are provided, one renamed per session. Where a task says "
                "Evidence.rtf or \u201cthe Evidence Document\u201d, open the one listed here for that "
                "task:", size=9, color=MUTED)
        for dest, _orig, _sess, who in renamed:
            sh.text(f"{dest}  \u2014  {', '.join('Task ' + t for t in who) if who else 'see task'}",
                    size=9, x=76)
        sh.y += 4
    sh.text("A scenario reprinted from its original paper may name a file that is not in the "
            "list above. Those belong to tasks that are not in this paper; ignore them.",
            size=9, color=MUTED)


def task_table(sh, rows, total, *, heading):
    sh.y += 6
    sh.text(heading, size=10, font="hebo")
    sh.y += 6
    cols = [(56, "Task"), (102, "Topic"), (306, "From"), (505, "Marks")]
    sh.room(30)
    for x, t in cols:
        sh.page.insert_text((x, sh.y), t, fontname="hebo", fontsize=8.5, color=MUTED)
    sh.y += 6
    sh.rule(pad=15, w=0.6)
    for task, topic, origin, marks in rows:
        sh.room(14)
        sh.page.insert_text((56, sh.y), str(task), fontname="helv", fontsize=9.5, color=INK)
        sh.page.insert_text((102, sh.y), topic[:44], fontname="helv", fontsize=9.5, color=INK)
        sh.page.insert_text((306, sh.y), origin, fontname="helv", fontsize=8.5, color=MUTED)
        mk = str(marks)
        sh.page.insert_text((531 - pymupdf.get_text_length(mk, fontname="helv", fontsize=9.5),
                             sh.y), mk, fontname="helv", fontsize=9.5, color=INK)
        sh.y += 13.5
    sh.rule(pad=15, w=0.6)
    sh.page.insert_text((56, sh.y), "Total", fontname="hebo", fontsize=10, color=INK)
    tot = str(total)
    sh.page.insert_text((531 - pymupdf.get_text_length(tot, fontname="hebo", fontsize=10), sh.y),
                        tot, fontname="hebo", fontsize=10, color=INK)
    sh.y += 22


def cover(doc, *, kind, name, subtitle, rows, total, files=(), renamed=()):
    """QUESTIONS gets a real front page then the task map; MARK SCHEME gets the map and
    the caveats a marker needs before they start awarding anything."""
    sh = Sheet(doc)
    if kind == "QUESTIONS":
        front_matter(sh, name=name, subtitle=subtitle, total=total, files=files,
                     renamed=renamed)
        sh.y = 1000  # the task map starts its own page, as page 2 of a real paper does
        sh.room(1)
        task_table(sh, rows, total, heading="TASK LIST")
        sh.text("Every task is a whole Cambridge question, kept in one piece and cited to the "
                "paper it came from. Marks are shown so you can budget: read the whole list "
                "before you start and give the big builds the time they are worth.",
                size=9.5, color=MUTED)
    else:
        sh.text(f"MARK SCHEME — AS Practical {name}", size=13, font="hebo")
        sh.y += 4
        sh.text(subtitle, size=10, color=MUTED)
        sh.y += 8
        sh.rule()
        task_table(sh, rows, total, heading="TASK LIST")
        sh.text("BEFORE YOU MARK", size=10, font="hebo")
        sh.y += 4
        for b in ("Pages are the finest grain these pre-2020 mark schemes allow: Cambridge laid "
                  "them out as screenshots under loose headings, with no per-question rows to "
                  "cut to. Each page is banner-labelled with the task or tasks it answers, in "
                  "paper order.",
                  "A page may carry more criteria than its tasks are worth. The video and audio "
                  "schemes are written per finished artefact, not per question, so a page lists "
                  "the whole original build \u2014 including steps this paper does not set. Award "
                  "only the criteria that match the tasks in the banner; the task list above "
                  "gives each task's tariff, and those tariffs are the ceiling.",
                  "For the same reason a page may show answers to questions that are not in "
                  "this paper at all. Ignore them."):
            sh.room(13)
            sh.page.draw_circle((65, sh.y - 3), 1.9, color=None, fill=MUTED)
            sh.text(b, x=76, width=463, size=9.5, color=MUTED)
            sh.y += 4
    return sh.pages


def build(name, spec, report):
    out = OUT_ROOT / name.replace(" ", "_")
    out.mkdir(parents=True, exist_ok=True)
    marks_cache, rows, task = {}, [], 0
    q_doc = pymupdf.open()
    flow = poc.PageFlow(q_doc)
    ms_order, ms_seen = [], {}
    src_files, task_of = {}, {}

    for blk in spec["blocks"]:
        paper = blk["paper"]
        marks_cache.setdefault(paper, bpc.marks_for(paper))
        first_task = task + 1
        qp = bpc.paper_dir(paper) / f"{paper}.pdf"
        if blk.get("pre"):
            span = (preamble_span(qp, blk["qnums"][0]) if blk["pre"] is True
                    else preamble_from(qp, blk["qnums"][0], blk["pre"]))
            if span:
                pi, t, bm = span
                src = pymupdf.open(qp)
                flow.place(src, pi, pymupdf.Rect(poc.LEFT_MARGIN, t, poc.RIGHT_MARGIN, bm),
                           f"Read before Task {first_task}  ·  {label_of(paper)}  ·  scenario and rubric",
                           None)
                src.close()
        for q in blk["qnums"]:
            task += 1
            spans = crop_spans(qp, paper, q)
            clips = [(pi, pymupdf.Rect(poc.LEFT_MARGIN, t, poc.RIGHT_MARGIN, b))
                     for pi, t, b in spans]
            src = pymupdf.open(qp)
            flow.place(src, spans[0][0], clips, f"Task {task}  ·  {label_of(paper)}", q)
            src.close()
            task_of[(paper, q)] = task
            note = gloss_for(paper, q, task_of)
            if note:
                if flow.cursor > poc.PAGE_H - poc.BOTTOM_MARGIN - 24:
                    flow._new_page()
                flow.page.insert_text((poc.LEFT_MARGIN + 26, flow.cursor + 2), flat(note),
                                      fontname="hebo", fontsize=8.5, color=ACCENT)
                flow.cursor += 16
            rows.append((task, blk["topic"], f"{label_of(paper)} Q{q}", marks_cache[paper][q]))
        rng = f"Task {first_task}" if first_task == task else f"Tasks {first_task}-{task}"
        # One page often answers two blocks at once (s19 p4 carries both the database
        # evaluation and the audio rubric). Claiming it for whichever block asked first
        # left the other block looking unmarked, so a page collects every block on it.
        for p in blk["ms"]:
            if (paper, p) in ms_seen:
                ms_order[ms_seen[(paper, p)]][2].append((rng, blk["topic"]))
            else:
                ms_seen[(paper, p)] = len(ms_order)
                ms_order.append([paper, p, [(rng, blk["topic"])]])
        for f in files_for(paper, blk["qnums"]):
            src_files.setdefault((sess_of(paper), f), None)

    total = sum(r[3] for r in rows)
    kw = {"garbage": 4, "deflate": True, "clean": True}

    # Copy the sources first: the QP front page has to print their final names, and two
    # sessions' Evidence.rtf only get their per-session names at copy time.
    sdir = out / "source"
    if sdir.exists():
        shutil.rmtree(sdir)
    sdir.mkdir()
    dupes = [f for _, f in src_files]
    copied, renamed = [], []
    for sess, f in src_files:
        # Evidence.rtf ships once per session; two of them in one folder would collide
        dest = f if dupes.count(f) == 1 else f"{Path(f).stem}_{sess}{Path(f).suffix}"
        shutil.copy2(ROOT / "SourceFiles/extracted" / SF[sess] / f, sdir / dest)
        copied.append(dest)
        if dest != f:
            who = [str(t) for t, _tp, origin, _m in rows if origin.startswith(sess_label(sess))]
            renamed.append((dest, f, sess, who))

    cover(flow.out_doc, kind="QUESTIONS", name=name, subtitle=spec["subtitle"],
          rows=rows, total=total, files=sorted(copied), renamed=renamed)
    # Banner last, over the cover sheets as well: a real paper numbers every page, and
    # numbering only the question sheets left a 8-sheet PDF footed "page 1 of 6".
    n = flow.out_doc.page_count
    for i, page in enumerate(flow.out_doc, 1):
        leaf_pdf.banner(page, left=f"QUESTIONS · AS Practical {name}", right=f"page {i} of {n}")
    flow.out_doc.save(out / "QP.pdf", **kw)
    flow.out_doc.close()

    ms_doc = pymupdf.open()
    for paper, p, who in ms_order:
        ms = bpc.paper_dir(paper) / f"{paper.replace('_qp_', '_ms_')}.pdf"
        src = pymupdf.open(ms)
        ms_doc.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        leaf_pdf.banner(ms_doc[-1], left="  +  ".join(f"{r} · {t}" for r, t in who),
                        right=f"{label_of(paper)} · mark scheme p{p}")
        src.close()
    cover(ms_doc, kind="MARK SCHEME", name=name, subtitle=spec["subtitle"],
          rows=rows, total=total)
    ms_doc.save(out / "MS.pdf", **kw)
    ms_doc.close()

    lines = [f"# AS Practical {name}", "", spec["subtitle"], "",
             f"**{total} marks.** Time allowed: {DURATION}.", "",
             f"Cambridge sets 90 marks in 2 h 30 for the current Paper 2, and set 110 marks in "
             f"2 h 30 for the 2017\u20132019 papers these tasks come from. {DURATION} clears both "
             f"rates for {total} marks, so nobody runs out of clock on a paper built to cover "
             f"four topics at once.", "",
             "| Task | Topic | Original question | Marks | Score |",
             "| ---: | --- | --- | ---: | ---: |"]
    lines += [f"| {t} | {topic} | {origin} | {m} | |" for t, topic, origin, m in rows]
    lines += [f"| | | **Total** | **{total}** | |", "",
              "## Source files", ""] + [f"- `{f}`" for f in sorted(copied)]
    if renamed:
        lines += ["", "Two sessions each ship an `Evidence.rtf` with their own skeleton, so they "
                  "are suffixed here, and the QP front page says so. Where a task says "
                  "`Evidence.rtf` or \"the Evidence Document\", use the one from its own session:",
                  ""]
        lines += [f"- `{dest}` — for {', '.join('Task ' + t for t in who)}" if who
                  else f"- `{dest}` (originally `{orig}`)"
                  for dest, orig, sess, who in renamed]
    lines += ["", "## Mark scheme", "",
              "`MS.pdf` holds the mark scheme pages for these tasks in paper order, each "
              "banner-labelled with the task or tasks it answers:", ""]
    lines += [f"- {', '.join(f'{r} — {t}' for r, t in who)} — {label_of(p)} page {pg}"
              for p, pg, who in ms_order]
    lines += ["", "Pre-2020 practical mark schemes are screenshots under loose headings with no "
              "per-question rows, so whole pages are the finest grain that does not risk pairing "
              "a task with the wrong answer.", "",
              "**A page can list more criteria than its tasks are worth.** The video and audio "
              "schemes are written per finished artefact, not per question, so a page spells out "
              "the whole original build including steps this paper does not set. Mark only the "
              "criteria that match the banner's tasks, and treat the tariffs in the table above "
              "as the ceiling. The same page may also answer questions that are not in this "
              "paper at all.", ""]
    (out / "notes.md").write_text("\n".join(lines))

    report.append(f"- **{name}** — {len(rows)} tasks, {total} marks, "
                  f"{len(copied)} source files, {len(ms_order)} mark scheme pages")
    return total, rows


def _check():
    """One runnable check: the blocks are marks-consistent, nothing is examined twice
    across the three papers, every named source file exists, every crop override still
    lands inside its page, and every task ends up with a tariff on the page."""
    seen = {}
    for name, spec in MOCKS.items():
        tot = 0
        for blk in spec["blocks"]:
            paper = blk["paper"]
            m = bpc.marks_for(paper)
            qp = bpc.paper_dir(paper) / f"{paper}.pdf"
            doc = pymupdf.open(qp)
            for q in blk["qnums"]:
                key = (paper, q)
                assert key not in seen, f"{key} used by both {seen[key]} and {name}"
                seen[key] = name
                assert m.get(q), f"no marks for {key}"
                tot += m[q]
                spans = crop_spans(qp, paper, q)
                for pi, top, bot in spans:
                    assert 0 <= top < bot <= doc[pi].rect.height, \
                        f"{key} crop {top}-{bot} off page {pi + 1}"
                # The tariff is the one thing a cropped task cannot do without: it is how
                # the candidate budgets and how the marker knows the ceiling. s19 Q4 lost
                # its "[5]" to a crop that stopped at the top of its own figure and the
                # paper shipped that way, so every task is now asked for it explicitly.
                body = "".join(doc[pi].get_text(clip=pymupdf.Rect(0, top, 595, bot))
                               for pi, top, bot in spans)
                tariffs = [int(x) for x in re.findall(r"\[\s*(\d+)\s*\]", body)]
                # A lettered question (s17 Q1 runs (a) to (i)) prints one tariff per
                # part and none for the whole, so the parts have to sum to the total.
                # An earlier version let any "(a)" in the crop skip the check outright,
                # which silently exempted Mock C's 55-mark Task 1 - 41% of that paper.
                assert m[q] in tariffs or sum(tariffs) == m[q], \
                    f"{key}: crop shows tariffs {tariffs}, need [{m[q]}] or parts summing to it"
            doc.close()
            for f in files_for(paper, blk["qnums"]):
                pth = ROOT / "SourceFiles/extracted" / SF[sess_of(paper)] / f
                assert pth.exists(), f"missing source {pth}"
            ms = bpc.paper_dir(paper) / f"{paper.replace('_qp_', '_ms_')}.pdf"
            n = pymupdf.open(ms).page_count
            assert max(blk["ms"]) <= n, f"{paper} ms page {max(blk['ms'])} > {n}"
        assert 90 <= tot <= 140, f"{name} is {tot} marks"
        dbq = [b for b in spec["blocks"] if b["topic"].startswith("10 ")]
        assert dbq, f"{name} has no database block"
        print(f"ok  {name}: {tot} marks, {sum(len(b['qnums']) for b in spec['blocks'])} tasks")
    print("ok  no question appears in two mocks; sources, crops and tariffs all present")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.check:
        return _check()
    report = ["# AS mock papers build report", ""]
    for name, spec in MOCKS.items():
        build(name, spec, report)
    (ROOT / "Reports").mkdir(exist_ok=True)
    (ROOT / "Reports/mock_papers_report.md").write_text("\n".join(report))
    print("\n".join(report))


if __name__ == "__main__":
    main()
