"""
Full pipeline: read every By Topic/Paper N/*.md chapter file and produce a
matching pair of print-ready PDFs (questions, answers) per chapter, cropped
straight out of the original PDFs the same way scripts/poc_chapter_pdf.py
proved out - native vector clips, packed A4 pages, per-item citation.

Adds two things the POC didn't need for its 3 hand-picked examples:
  - parsing By Topic markdown to drive the whole corpus instead of a
    hardcoded EXAMPLES list
  - sub-part cropping ("8(a)", "10(a)(i)") since most real entries are a
    part of a question, not the whole thing

Zone-variant / cross-paper duplicate rows (headers naming two papers, e.g.
"P 11 + 12") always use the FIRST paper listed - see README.md's note on
CAIE reprinting the same paper across zone variants.

USAGE: scripts/venv/bin/python3 scripts/build_chapterwise_pdfs.py ["Paper 1" "Paper 3" ...]
                                                                   [--out DIR]
       (no argument = every By Topic paper; naming papers rebuilds only those and
        writes the skip log to chapterwise_build_report (Paper 1, Paper 3).md instead;
        --out writes the packs, and the report, under DIR instead of Chapterwise PDFs/)
OUTPUT: Chapterwise PDFs/Paper N/<chapter> - Questions.pdf (+ Answers.pdf,
        + Questions (write-on).pdf unless the paper is in NO_WRITE_ON)
        Reports/chapterwise_build_report.md (per-entry skip log + counts)
        Run label_theory.py afterwards for the covers and page banners.
"""

import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import poc_chapter_pdf as poc  # PageFlow, get_lines, draw_ms_header, margins, find_answer_row, sp
import ms_pages  # which pages of a free-text practical mark scheme answer which task

ROOT = Path(__file__).parent.parent
BY_TOPIC = ROOT / "By Topic"
PDF_ROOT = ROOT / "PDFs"
OUT_ROOT = ROOT / "Chapterwise PDFs"
REPORT_PATH = ROOT / "Reports" / "chapterwise_build_report.md"

SESSION_NAME = {"S": "May/June", "W": "October/November", "M": "February/March"}

# Papers whose candidates answer on a computer (the practicals): the question paper prints
# no answer space, so a write-on file would be invented lines. Papers 1 and 3 print their
# own answer space on every paper (audit phase 4, necessity/it.md: 64/64 and 59/59).
NO_WRITE_ON = {"2", "4"}

HEADER_RE = re.compile(r"^#### P (\d+)(?: \+ (\d+))? \| ([SWM]) (\d{4}) \|(.*)$")
LINK_RE = re.compile(r"\[\[([^|\]]+)\|(?:Question|Answer)[^\]]*\]\]")
FILE_PAPER_CODE_RE = re.compile(r"_(?:qp|ms)_(\d+)\.pdf$")

SUBPART_LETTER_RE = re.compile(r"^\(([a-h])\)")
SUBPART_ROMAN_RE = re.compile(r"^\(([ivx]{1,4})\)")
LETTER_X_RANGE = (60, 85)
ROMAN_X_RANGE = (85, 115)
SUBPART_LABEL_RE = re.compile(r"\(?([a-h]|[ivx]{1,4})\)?")
# Trailing matter that belongs to no question - the last question in a paper must not
# absorb it just by being last. Matched per page, not per line: only the first line of
# the copyright notice is recognisable, but the whole page has to go with it.
END_MATTER_RE = re.compile(r"BLANK PAGE|Permission to reproduce items where third-party"
                           r"|Cambridge Assessment International Education is part of", re.I)
# What CAIE actually prints in the bottom margin: copyright, paper code, "[Turn over", the
# download site's stamp. Only these (and security noise, see is_noise) are boilerplate in
# the footer zone. The zone itself is NOT: a last answer line and its "[8]" often sit at
# y 770-799 on an 842pt page, and dropping every line in the bottom 60pt cut the mark and
# the answer space off the crop (ledger P0-PRIOR-014).
FOOTER_TEXT_RE = re.compile(r"UCLES|\b\d{4}/\d{2}/\s*[A-Z]\s*/\s*[A-Z]\s*/\s*\d{2}\b|Turn over"
                            r"|dynamicpapers|^DC \([A-Z]+\)", re.I)


def is_noise(text, top, bottom):
    """2024+ papers carry per-copy security strings: tiny (about 5pt) lines of mojibake
    with no ASCII letter or digit, anywhere on the page. They are not content, and one
    printed near the top of a page used to stretch the crop of the question below it up
    over the whole question above it (ledger P0-PRIOR-013, 9626_s24_qp_13 Q4)."""
    return bottom - top < 7 and not re.search(r"[A-Za-z0-9]", text)


# ── By Topic markdown parsing ────────────────────────────────────────────
def parse_chapter_md(path):
    """[{qp, ms, qnum, label}, ...] in file order, one per question-part
    entry. Only the header line + the "No." column of the question table
    matter here - the question/answer prose in the .md is for topic tagging,
    not needed since we crop straight from the source PDF."""
    lines = path.read_text().split("\n")
    entries = []
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if not m:
            continue
        p1, p2, session, year, rest = m.groups()
        links = LINK_RE.findall(rest)
        if len(links) < 2:
            continue
        qp_name, ms_name = links[0], links[1]

        qnum_line = None
        for j in range(i + 1, min(i + 8, len(lines))):
            if lines[j].startswith("| No."):
                qnum_line = lines[j + 2] if j + 2 < len(lines) else None
                break
        if not qnum_line:
            continue
        qm = re.match(r"^\|\s*([^|]+?)\s*\|", qnum_line)
        if not qm:
            continue
        qnum = qm.group(1).split("/")[0].strip()

        code_m = FILE_PAPER_CODE_RE.search(qp_name)
        paper_code = code_m.group(1) if code_m else p1
        label = f"9626/{paper_code} {SESSION_NAME.get(session, session)} {year}"
        entries.append({"qp": qp_name, "ms": ms_name, "qnum": qnum, "label": label})
    return entries


# ── question-side cropping (with sub-part narrowing) ─────────────────────
def collect_blocks(doc, practical=False):
    """Every top-level question's (qnum, page_index, top, bottom, lines) in
    the paper, same left-margin-bold-number detection split_papers.py uses.
    Kept as one full pass (not stop-at-first-match) since sub-part lookups
    need the block's own line list to search within afterwards.

    `practical` (Papers 2 and 4): the scenario Cambridge prints after one task's
    tariff and before the next task's number goes to the next task (see
    hand_over_preambles). Every paper: drawn figures widen the span of the question
    they belong to (see attach_drawings)."""
    require_bold = poc.sp.doc_has_named_bold_font(doc)
    blocks = []
    current = None
    page_draws = []          # (page_index, [drawing cluster Rects], footer_y, end_y)
    for pi, page in enumerate(doc):
        ph = page.rect.height
        # Top-down order, not content-stream order: a line the stream emits after a
        # question number but that sits ABOVE it on the page used to stretch that
        # question's crop up over the previous question. A question-number line wins a
        # tie with the text beside it.
        lines = sorted(poc.get_lines(page, require_bold),
                       key=lambda ln: (ln[1] - (3 if ln[3] is not None else 0)))
        # On a long paper the copyright notice gets a page to itself; on a short one it
        # sits under the last questions. Cut at where it starts rather than dropping the
        # page, so the last question keeps its content but not Cambridge's back matter.
        ends = [top for t, top, _, _ in lines if END_MATTER_RE.search(t)]
        end_y = min(ends) if ends else None
        # The footer starts where CAIE's footer text starts, not at a fixed 60pt: content
        # in the bottom zone (a last "......[8]" line) is kept, and every crop stops above
        # the real footer so a padded bottom edge cannot pull the copyright line in.
        # (a sane line height too: the rotated "DO NOT WRITE IN THIS MARGIN" runs the
        # full page height and must not be read as a footer starting at y=42)
        in_zone = [(t, top, bottom) for t, top, bottom, _ in lines
                   if bottom > ph - poc.FOOTER_ZONE and bottom - top < 30]
        foot = [top for t, top, bottom in in_zone
                if FOOTER_TEXT_RE.search(t) or is_noise(t, top, bottom)]
        footer_y = min(foot) if foot else ph - poc.FOOTER_ZONE / 3
        # Content above question 1 on question 1's own page (a practical paper's scenario:
        # "You work for Tawara Robotics ... like this:" and its picture) belongs to no
        # number, and was dropped from every crop. It is what the candidate reads before
        # question 1, so question 1 carries it (ledger P0-PRIOR-015).
        pre = []
        for ln in lines:
            if end_y is not None and ln[1] >= end_y:
                continue
            text, top, bottom, qnum = ln
            boiler = (top < poc.HEADER_ZONE or top >= footer_y or is_noise(text, top, bottom)
                      or (bottom > ph - poc.FOOTER_ZONE and FOOTER_TEXT_RE.search(text)))
            if boiler:
                continue
            lo, hi = top - poc.TOP_PAD, min(bottom + poc.BOTTOM_PAD, footer_y - 1)
            if qnum is not None and poc.sp.continues_sequence(qnum, current["qnum"] if current else None):
                current = {"qnum": qnum, "page": pi, "top": lo, "bottom": hi,
                           "lines": [(text, top, bottom, pi)], "spans": {pi: [lo, hi]}}
                if not blocks and pre:
                    current["top"] = current["spans"][pi][0] = min(p[1] for p in pre) - poc.TOP_PAD
                    current["lines"][:0] = [(t, a, b, pi) for t, a, b in pre]
                blocks.append(current)
            elif current is None:
                pre.append((text, top, bottom))
            else:
                # A question that runs past the foot of its opening page continues on the
                # next one until the next top-level number starts. Tracking only the start
                # page silently truncated every multi-page question to its first page.
                span = current["spans"].setdefault(pi, [lo, hi])
                span[0] = min(span[0], lo)
                span[1] = max(span[1], hi)
                if pi == current["page"]:
                    current["bottom"] = span[1]
                # Every page's lines, not just the opening page's: a part printed on a
                # later page ("8(c)(ii)" on page 3 of Q8) could not be found when only
                # page 1 was searched, and the crop silently fell back to the first
                # page - the earlier parts - under the later part's label (P0-PRIOR-013).
                current["lines"].append((text, top, bottom, pi))
        attach_images(page, pi, blocks, footer_y, end_y)
        page_draws.append((pi, drawing_clusters(page, footer_y, end_y)))
    if practical:
        hand_over_preambles(blocks)
    attach_drawings(blocks, page_draws)
    return blocks


# B3-crop-bounds (F-IT-PAGES-MISSING-PREAMBLE): the end of a practical task is its tariff
_TARIFF_RE = re.compile(r"\[\d{1,3}\]\s*$")
_EVIDENCE_RE = re.compile(r"^Evidence\s+\d+\b")


def hand_over_preambles(blocks):
    """Practical papers: give the next task the scenario printed above its number.

    Spans are built in reading order, so whatever Cambridge prints between one task's
    tariff "[n]" and the next task's number - the scenario of a new section ("Tawara
    Eco-Cars have provided the following information: ...", 9626_w21_qp_02 above Q5),
    the rubric ("All video clips produced must be of a professional standard", top of
    9626_m24_qp_02 p6 above Q4) and its pictures - was the tail of the task ABOVE it.
    The task below, which cannot be done without it, never showed it, and a pack of a
    different chapter showed it under the wrong task. A practical paper prints no answer
    space, so after a task's last tariff only its "Evidence N" box still belongs to it
    (the box follows the mark, 9626_s19_qp_02 Q15); everything else up to the next number
    is the next task's preamble. Theory papers are left alone: there an answer table or
    answer lines may follow the tariff."""
    for prev, cur in zip(blocks, blocks[1:]):
        lines = sorted(prev["lines"], key=lambda ln: (ln[3], ln[1], ln[2]))
        marks = [ln for ln in lines if _TARIFF_RE.search(ln[0])]
        if not marks:
            continue
        mark = max(marks, key=lambda ln: (ln[3], ln[2]))
        # strictly below the tariff's row: "e.g. n21video_ZZ999_9999 [1]" shares its row
        tail = [ln for ln in lines if (ln[3], ln[1]) > (mark[3], mark[2] - 2)]
        keep_n = 0
        while keep_n < len(tail) and _EVIDENCE_RE.match(tail[keep_n][0]):
            # the "Evidence N" box closes the task above: its heading and the lines
            # that follow it without a gap stay with that task
            end = tail[keep_n]
            keep_n += 1
            while (keep_n < len(tail) and tail[keep_n][3] == end[3]
                   and tail[keep_n][1] - end[2] <= 16):
                end = tail[keep_n]
                keep_n += 1
        moved = tail[keep_n:]
        if not any(t.strip() for t, *_ in moved):
            continue
        cur.setdefault("own_start", (cur["page"], cur["top"]))
        moved_ids = {id(ln) for ln in moved}
        prev["lines"] = [ln for ln in prev["lines"] if id(ln) not in moved_ids]
        old = {pi: list(span) for pi, span in prev["spans"].items()}
        for pi in {ln[3] for ln in moved}:
            kept = [ln for ln in prev["lines"] if ln[3] == pi]
            lo, hi = old[pi]
            if kept:
                prev["spans"][pi] = [max(lo, min(ln[1] for ln in kept) - poc.TOP_PAD),
                                     min(hi, max(ln[2] for ln in kept) + poc.BOTTOM_PAD)]
            elif pi != prev["page"]:
                del prev["spans"][pi]
            span = cur["spans"].setdefault(pi, [hi, lo])
            on_pi = [ln for ln in moved if ln[3] == pi]
            span[0] = min(span[0], max(lo, min(ln[1] for ln in on_pi) - poc.TOP_PAD))
            span[1] = max(span[1], min(hi, max(ln[2] for ln in on_pi) + poc.BOTTOM_PAD))
        if prev["page"] in prev["spans"]:
            prev["top"], prev["bottom"] = prev["spans"][prev["page"]]
        cur["lines"][:0] = sorted(moved, key=lambda ln: (ln[3], ln[1]))
        cur["page"] = min(cur["spans"])
        cur["top"], cur["bottom"] = cur["spans"][cur["page"]]


def drawing_clusters(page, footer_y, end_y):
    """Drawn figures on a question page that could belong to a question: flowcharts,
    vector pictures, tables. Not the corner registration marks, margin strips, full-page
    frames, the header or the footer, nor Cambridge's back matter."""
    pw, ph = page.rect.width, page.rect.height
    out = []
    try:
        clusters = page.cluster_drawings()
    except Exception:
        return out
    for r in clusters:
        if r.width < 30 or r.height < 8 or r.height > 0.9 * ph or r.width > pw - 40:
            continue
        if r.y1 <= poc.HEADER_ZONE or r.y0 >= footer_y or (end_y is not None and r.y0 >= end_y):
            continue
        out.append((pymupdf.Rect(r), footer_y, end_y))
    return out


def attach_drawings(blocks, page_draws):
    """Grow each question's span over the drawn figures that belong to it.

    Spans are built from text lines and raster images, so a figure drawn with vector
    paths was cut wherever its last text label ended: the 9626_s25_qp_13 Q13 flowchart
    lost its bottom 33pt (decision box and arrows) below "is count = 12?", the
    9626_m23_qp_04 Task 1 rocket lost 110pt below "[20]" (F-IT-PAGES-CLIP-OBJECT).
    A figure belongs to the question in progress at its vertical centre, like an image.
    A figure that also holds a line of another question is skipped, so this can never
    pull a neighbouring question in. Only the span grows; the figure is not added to
    the block's lines, so part-label narrowing and lead-in detection are unchanged."""
    if not blocks:
        return
    starts = [((b["page"], b["lines"][0][1]) if b["lines"] else (b["page"], b["top"]), b)
              for b in blocks]
    for pi, clusters in page_draws:
        for r, footer_y, end_y in clusters:
            mid = (pi, (r.y0 + r.y1) / 2)
            owner = None
            for start, b in starts:
                if start <= mid:
                    owner = b
            if owner is None:
                if blocks[0]["page"] != pi:
                    continue                # cover / instructions page
                owner = blocks[0]
            if any(b is not owner and any(lpi == pi and r.y0 - 2 <= (lt + lb) / 2 <= r.y1 + 2
                                          for _t, lt, lb, lpi in b["lines"])
                   for b in blocks):
                continue                    # shared with another question: leave it
            lo = max(r.y0, poc.HEADER_ZONE) - 4
            hi = min(r.y1 + 4, footer_y - 1)
            if end_y is not None:
                hi = min(hi, end_y - 1)
            span = owner["spans"].get(pi)
            if span is None:
                # a page holding only this figure: only for a page the question reaches
                if not any(lpi == pi for *_x, lpi in owner["lines"]):
                    continue
                span = owner["spans"].setdefault(pi, [lo, hi])
            span[0] = min(span[0], lo)
            span[1] = max(span[1], hi)
            if pi == owner["page"]:
                owner["top"] = min(owner["top"], span[0])
                owner["bottom"] = max(owner["bottom"], span[1])


def attach_images(page, pi, blocks, footer_y, end_y):
    """Grow each question's span on this page over the images that belong to it.

    Spans were built from text lines only, so a figure with no text beside it - a
    screenshot at the top of a continuation page, a "like this:" picture under the
    last line of a task - fell outside every crop and was silently dropped from the
    pack (ledger P0-PRIOR-015, figdrop_practical.json). An image belongs to the
    question in progress at its vertical centre, the same reading-order rule the
    text uses; one above question 1 on question 1's page is question 1's preamble.
    The image also goes into the block's lines (with empty text) so a part crop
    keeps a slice that holds only a figure."""
    if not blocks:
        return
    starts = [((b["page"], b["lines"][0][1]) if b["lines"] else (b["page"], b["top"]), b)
              for b in blocks]
    for im in page.get_image_info():
        x0, y0, x1, y1 = im["bbox"]
        if y1 - y0 < 5 or x1 - x0 < 5 or y1 - y0 > 0.9 * page.rect.height:
            continue                       # specks, rules, full-page backgrounds
        if y1 <= poc.HEADER_ZONE or y0 >= footer_y or (end_y is not None and y0 >= end_y):
            continue                       # header logo, footer, Cambridge back matter
        mid = (pi, (y0 + y1) / 2)
        owner = None
        for start, b in starts:
            if start <= mid:
                owner = b
        if owner is None:
            first = blocks[0]
            if first["page"] != pi:
                continue                   # cover / instructions page, not a question
            owner = first
        lo = max(y0, poc.HEADER_ZONE) - poc.TOP_PAD
        hi = min(y1 + poc.BOTTOM_PAD, footer_y - 1)
        if end_y is not None:
            hi = min(hi, end_y - 1)
        span = owner["spans"].setdefault(pi, [lo, hi])
        span[0] = min(span[0], lo)
        span[1] = max(span[1], hi)
        if pi == owner["page"]:
            owner["top"] = min(owner["top"], span[0])
            owner["bottom"] = max(owner["bottom"], span[1])
        owner["lines"].append(("", max(y0, poc.HEADER_ZONE), y1, pi))


def block_spans(block, preamble=True):
    """[(page_index, top, bottom), ...] for the whole question, in reading order.
    preamble=False leaves out a practical preamble handed over by hand_over_preambles
    (build_mock_papers prints that rubric on its own)."""
    spans = [(pi, tb[0], tb[1]) for pi, tb in sorted(block["spans"].items())]
    if not preamble and "own_start" in block:
        p0, t0 = block["own_start"]
        spans = [(pi, max(t, t0) if pi == p0 else t, b) for pi, t, b in spans if pi >= p0]
    return spans


# F-IT-P1-QA (fix 2): the end of a part's answer space - a "[N]" mark or a dot leader
_SPACE_END_RE = re.compile(r"\[\d{1,2}\]|(?:[.·…]\s?){20,}|^[.·…\s]{12,}$")


def _lead_in(block, start, end):
    """(page_index, y) where set-up text for the part labelled at `end` begins, or None.

    Looks between the previous label (`start`) and this one for the last line of answer
    space ("[N]" or dots); anything printed after it (text, a table, an image) is a
    lead-in. None when the previous part has no answer space to end it (a stem whose
    sub-parts carry the marks, a tick table) or nothing follows it."""
    lines = sorted((lpi, lt, lb, t) for t, lt, lb, lpi in block["lines"]
                   if start < (lpi, lt) < end)
    ends = [k for k, (_p, _t, _b, text) in enumerate(lines) if _SPACE_END_RE.search(text)]
    if not ends:
        return None
    after = [ln for ln in lines[ends[-1] + 1:] if ln[3].strip() or ln[2] - ln[1] > 5]
    if not after:
        return None
    return (after[0][0], after[0][1] - poc.TOP_PAD)


def narrow_to_part(block, labels):
    """[(page_index, top, bottom), ...] covering the target sub-part, PLUS any
    shared stem text CAIE printed once above the (a)/(b)/(c) (or (i)/(ii)) list
    at each level being narrowed into - e.g. "Describe how X could be used in
    each of the following scenarios:" sits above (a) but belongs to (b) and
    (c) just as much. Cropping straight to the target label alone silently
    drops that stem, so each level's pre-list text is kept as its own range
    and merged with the target range only where they're actually contiguous
    (true for the first sub-part at a level, where "stem" and "own content"
    are the same crop).

    Positions are (page_index, y) pairs, compared page first, so a part that
    starts or ends on a later page of the question is found and cropped across
    the page break. Returns None if a label cannot be found: the caller then
    falls back to the whole question, which at least contains the part - the old
    "best effort" crop showed the EARLIER parts under this part's label."""
    ranges = []
    top = (block["page"], block["top"])
    last = max(block["spans"])
    bottom = (last, block["spans"][last][1])
    for label in labels:
        is_roman = bool(re.fullmatch(r"[ivx]+", label))
        pat = SUBPART_ROMAN_RE if is_roman else SUBPART_LETTER_RE
        markers = []
        for text, ltop, _lbottom, lpi in block["lines"]:
            if not (top <= (lpi, ltop) < bottom):
                continue
            m = pat.match(text)
            if m:
                markers.append(((lpi, ltop), m.group(1)))
        markers.sort()
        idx = next((i for i, (_, lab) in enumerate(markers) if lab == label), None)
        if idx is None:
            return None
        stem_end = (markers[0][0][0], markers[0][0][1] - poc.TOP_PAD)
        if stem_end > top:
            ranges.append((top, stem_end))
        top = (markers[idx][0][0], markers[idx][0][1] - poc.TOP_PAD)
        # F-IT-P1-QA (fix 2): set-up text printed after an earlier part's answer space
        # and before the next label ("The spreadsheet has now been sorted." + the sorted
        # table, 9626_s21_qp_13 8(c)) introduces the part BELOW it, but the range above
        # gives it to the part above. The part's own lead-in now starts its range; the
        # lead-ins of earlier parts at this level are added too, since set-up carries
        # forward ("Explain what is meant by the following terms." sits above (b) but
        # serves (c), 9626_s20_qp_12 5). The earlier part keeps its copy as well.
        for j in range(1, idx + 1):
            lead = _lead_in(block, markers[j - 1][0], markers[j][0])
            if lead is None:
                continue
            if j == idx:
                top = lead
            else:
                ranges.append((lead, (markers[j][0][0], markers[j][0][1] - poc.TOP_PAD)))
        bottom = markers[idx + 1][0] if idx + 1 < len(markers) else bottom
    ranges.append((top, bottom))
    # (page, y) ranges -> per-page slices, each page limited to the question's own
    # extent on it, and a slice kept only if some line of the question starts in it
    # (the gap between a page's last line and the next page's first marker is empty).
    out = []
    for (pa, ya), (pb, yb) in ranges:
        for pi in range(pa, pb + 1):
            if pi not in block["spans"]:
                continue
            s_top, s_bot = block["spans"][pi]
            t = ya if pi == pa else s_top
            b = yb if pi == pb else s_bot
            if b - t < 1 or not any(lpi == pi and t <= lt < b
                                    for _x, lt, _y, lpi in block["lines"]):
                continue
            if out and out[-1][0] == pi and t <= out[-1][2] + 1:
                out[-1] = (pi, out[-1][1], max(out[-1][2], b))
            else:
                out.append((pi, t, b))
    return out


# The same qp/ms PDF gets referenced by many different chapters (one paper
# touches many syllabus topics), so caching the expensive per-document scan
# (full-text line extraction, table detection) once per file - instead of
# once per entry that happens to reference it - is the difference between
# scanning ~250 unique source PDFs and rescanning them thousands of times
# over a 2000+ entry run. Keyed for the whole process lifetime.
_qp_block_cache: dict[str, list] = {}
CROP_WARNINGS: list[str] = []   # parts that fell back to the whole question
WRITE_ON_TAILS: list[str] = []  # write-on parts that got invented lines (no own space)
_ms_row_cache: dict[str, list] = {}


_upright_cache: dict[str, bytes | None] = {}


def open_upright(path):
    """Open a source PDF with any /Rotate baked into the page content.

    About a fifth of CAIE mark schemes ship landscape pages as portrait media with
    /Rotate 90. PyMuPDF reports text and table coordinates in the UNROTATED frame,
    but show_pdf_page also draws the content unrotated, so a crop taken from such a
    page arrives in the pack on its side and cut across the columns instead of
    along the rows. Baking the rotation once puts every coordinate downstream in
    one frame.

    ponytail: rebuilds the whole document rather than the rotated pages only - page
    numbering has to stay 1:1 with the original, and a half-normalised document is
    exactly the bug this removes.
    """
    key = str(path)
    if key not in _upright_cache:
        src = pymupdf.open(path)
        if any(pg.rotation for pg in src):
            out = pymupdf.open()
            for pg in src:
                disp = pymupdf.Rect(pg.rect)   # rotation-aware, so already landscape
                rot = pg.rotation
                pg.set_rotation(0)             # or show_pdf_page fits the wrong box
                out.new_page(width=disp.width, height=disp.height).show_pdf_page(
                    pymupdf.Rect(0, 0, disp.width, disp.height), src, pg.number,
                    rotate=-rot)
            _upright_cache[key] = out.tobytes()
            out.close()
        else:
            _upright_cache[key] = None         # nothing to do, open the file as-is
        src.close()
    data = _upright_cache[key]
    return pymupdf.open(path) if data is None else pymupdf.open(stream=data,
                                                                filetype="pdf")


def get_qp_blocks(qp_path):
    key = str(qp_path)
    if key not in _qp_block_cache:
        doc = open_upright(qp_path)
        code = FILE_PAPER_CODE_RE.search(Path(qp_path).name)
        _qp_block_cache[key] = collect_blocks(
            doc, practical=bool(code) and code.group(1).lstrip("0")[:1] in ("2", "4"))
        doc.close()
    return _qp_block_cache[key]


def get_ms_rows(ms_path):
    """[(row_label, page_index, bbox), ...] for every labelled row in every
    table in the mark scheme, found once and reused for every qnum lookup
    against this file."""
    key = str(ms_path)
    if key not in _ms_row_cache:
        doc = open_upright(ms_path)
        rows = []
        for pi, page in enumerate(doc):
            for table in page.find_tables():
                for i, row in enumerate(table.extract()):
                    if row and row[0] and str(row[0]).strip():
                        rows.append((str(row[0]).strip(), pi, table.rows[i].bbox))
        doc.close()
        _ms_row_cache[key] = rows
    return _ms_row_cache[key]


MS_TABLE_MAX_X0 = 150   # a mark-scheme task table starts at the left margin (x 40-60)


def find_answer_range(ms_path, qnum_target):
    """Usually an exact row-label match is enough. But some By Topic
    entries keep a question whole ("6") because its mark scheme couldn't be
    reliably matched part-by-part (README: kept whole rather than risk
    pairing a part with the wrong answer) - CAIE's own MS table still
    splits those into "6(i)"/"6(ii)" rows, so there's no exact "6" row to
    find. Falls back to the union of every row starting with "<qnum>(" on
    whichever page has the most of them."""
    # B3-crop-bounds (F-IT-PAGES-OBJECT-NEVER-SHOWN): a row is a task-table row only if
    # the table starts at the left margin. 2017-2021 screenshot mark schemes put a small
    # marks box beside each screenshot (9626_s17_ms_02 p2: "1a | Insert row - 51 pt | 1"
    # at x=311), whose "1" matched task 1, so the pack showed that box and none of the
    # seven screenshots of the answer. Such a mark scheme has no task rows: the caller's
    # page fallback (find_answer_pages / ms_pages) then shows the task's pages.
    rows = [r for r in get_ms_rows(ms_path) if r[2][0] < MS_TABLE_MAX_X0]
    for label, pi, bbox in rows:
        if label == qnum_target:
            return pi, bbox
    by_page: dict[int, list] = {}
    for label, pi, bbox in rows:
        if label.startswith(qnum_target + "("):
            by_page.setdefault(pi, []).append(bbox)
    if by_page:
        pi, bboxes = max(by_page.items(), key=lambda kv: len(kv[1]))
        x0, y0 = min(bb[0] for bb in bboxes), min(bb[1] for bb in bboxes)
        x1, y1 = max(bb[2] for bb in bboxes), max(bb[3] for bb in bboxes)
        return pi, (x0, y0, x1, y1)
    raise ValueError(f"answer row {qnum_target} not found")


# F-IT-P1-QA (fix 1): theory mark-scheme answers across pages. find_answer_range (above)
# returns ONE row, or the rows on ONE page, so a theory answer lost (i) rows on other pages
# (9626_s18_ms_13 Q8 started at 8(a)(iii)), (ii) a row's continuation overleaf, where CAIE
# repeats the label or leaves it empty (9626_w18_ms_11 Q12 lost its indicative content),
# and (iii) an exact label match could hit a row of a table drawn INSIDE an answer cell
# (9626_s19_ms_13 Q9 matched a "9|9|9" tick row; the tick glyph extracts as "9").
_ms_part_cache: dict[str, list] = {}


def get_ms_part_rows(ms_path):
    """[(label or None, page_index, bbox, continues), ...]: every row of every TOP-LEVEL
    table of a theory mark scheme, in reading order, column-header rows left out. label is
    the first cell with whitespace removed ("8(a) (i)" -> "8(a)(i)"), None when empty (the
    rest of a row split over a page break, or a merged label cell). `continues` marks the
    first row of the first table on a page when that table starts at the top of the page,
    i.e. where a row cut by the page break carries on."""
    key = str(ms_path)
    if key not in _ms_part_cache:
        doc = open_upright(ms_path)
        out = []
        for pi, page in enumerate(doc):
            tables = list(page.find_tables())
            boxes = [pymupdf.Rect(t.bbox) for t in tables]
            tops = sorted((boxes[ti].y0, ti) for ti in range(len(tables))
                          if not any(j != ti and boxes[j] != boxes[ti]
                                     and boxes[j].contains(boxes[ti])
                                     for j in range(len(tables))))
            first = True
            for n, (y0, ti) in enumerate(tops):
                t = tables[ti]
                for i, row in enumerate(t.extract()):
                    cells = [str(c or "").strip() for c in (row or [])]
                    if all(c.lower() in HEADER_CELLS for c in cells):
                        continue
                    label = re.sub(r"\s", "", cells[0]) if cells else ""
                    out.append((label or None, pi, tuple(t.rows[i].bbox),
                                first and n == 0 and y0 <= CONTINUATION_TOP))
                    first = False
        doc.close()
        _ms_part_cache[key] = out
    return _ms_part_cache[key]


def find_answer_spans_theory(ms_path, qnum_target):
    """[(page_index, (x0, y0, x1, y1)), ...] - the whole mark-scheme answer for a theory
    question or part, across every page it runs over, in reading order.

    Rows taken: the first row labelled exactly `qnum_target`, else every row whose label
    starts with "<qnum>(" (on any page). Each taken row brings the unlabelled rows under it
    and, overleaf, a first row that is unlabelled or repeats its label. Contiguous rows on
    a page are one clip; a page break or a skipped row starts a new clip."""
    rows = get_ms_part_rows(ms_path)
    q = re.sub(r"\s", "", qnum_target)
    picks = [i for i, r in enumerate(rows) if r[0] == q][:1]
    if not picks:
        picks = [i for i, r in enumerate(rows) if r[0] and r[0].startswith(q + "(")]
    if not picks:
        raise ValueError(f"answer row {qnum_target} not found")
    take = set()
    for i in picks:
        take.add(i)
        j = i + 1
        while j < len(rows):
            lab, pi, _bb, cont = rows[j]
            same_page = pi == rows[j - 1][1]
            if lab is None and (same_page or cont):
                take.add(j)                       # rest of the row / merged label cell
            elif lab == rows[i][0] and cont and pi == rows[j - 1][1] + 1:
                take.add(j)                       # CAIE repeats the label overleaf
            else:
                break
            j += 1
    clips, prev = [], None
    for ix in sorted(take):
        _lab, pi, bb, _c = rows[ix]
        if clips and clips[-1][0] == pi and prev == ix - 1:
            x0, y0, x1, y1 = clips[-1][1]
            clips[-1] = (pi, (min(x0, bb[0]), min(y0, bb[1]), max(x1, bb[2]), max(y1, bb[3])))
        else:
            clips.append((pi, tuple(bb)))
        prev = ix
    return clips


_ms_task_cache: dict[str, list] = {}
CONTINUATION_TOP = 130   # a table starting above this on a page continues the last one
HEADER_CELLS = {"", "question", "answer", "marks", "task", "mark"}
TASK_ROW_RE = re.compile(r"^(\d{1,2})(?:\(|\s|$)")          # "1(a)", "2", "2 Data Base"
# "Task 4 - Webpage / Candidate file ...", "Task 1(a) - Database", "See task 3 below for
# examples": a row naming a task in words. Inside that task's rows it is a sub-heading;
# before them it heads them (or, in the 2022 layout, IS the task's row); after another
# task's rows it opens an appendix of candidate evidence that re-marks the same points
# (9626_s23_ms_04 pp 8-16), which must not be counted twice.
TASK_HEAD_RE = re.compile(r"^(?:See\s+)?Tasks?\s*(\d{1,2})", re.I)


def get_ms_task_rows(ms_path):
    """[(task or None, page_index, bbox), ...] for every row of every top-level table,
    in reading order. Unlike get_ms_rows it keeps rows with an empty or non-label first
    cell - the second half of a row split over a page break, a "Total marks" line, a
    worked-example sub-table - and gives each the task of the labelled row above it."""
    key = str(ms_path)
    if key not in _ms_task_cache:
        doc = open_upright(ms_path)
        out, current, numbered = [], None, set()
        for pi, page in enumerate(doc):
            tables = list(page.find_tables())
            boxes = [pymupdf.Rect(t.bbox) for t in tables]
            # a table drawn inside an answer cell is part of that row, not a new row
            tops = sorted((boxes[ti].y0, ti) for ti in range(len(tables))
                          if not any(j != ti and boxes[j] != boxes[ti]
                                     and boxes[j].contains(boxes[ti])
                                     for j in range(len(tables))))
            heads = ms_task_headings(page, boxes)
            for n, (y0, ti) in enumerate(tops):
                # Only the first table on a page, starting at the top of it, can carry on
                # the previous page's task (a row split by the page break). Any other new
                # table - the next task's grid, an appendix of candidate evidence - does
                # not inherit a task until a labelled row says which one it is.
                # B3-crop-bounds: nor does a table under a "Task N" heading printed
                # above it (9626_m22_ms_02 p8: the appendix's "Task 2" Trips table was
                # taken as the rest of task 5, two pages after task 5 had ended).
                if n or y0 > CONTINUATION_TOP or any(y < y0 and t != current
                                                     for t, y, _p in heads):
                    current = None
                t = tables[ti]
                for i, row in enumerate(t.extract()):
                    label = str(row[0] or "").strip() if row else ""
                    bbox = t.rows[i].bbox
                    cells = [str(c or "").strip().lower() for c in (row or [])]
                    m = TASK_ROW_RE.match(label)
                    h = TASK_HEAD_RE.match(label)
                    if m:
                        current = m.group(1)
                        numbered.add(current)
                    elif h and h.group(1) != current:
                        # ("Task 1(b) - Database" inside task 1's own rows is a sub-heading)
                        current = None if h.group(1) in numbered else h.group(1)
                        if current is None:
                            continue
                    elif all(c in HEADER_CELLS for c in cells) and (any(cells)
                                                                    or bbox[3] - bbox[1] < 15):
                        # the column header (or a sliver of it): CAIE repeats it at the top
                        # of every page, but one further down opens the next task's grid
                        if any(cells) and bbox[1] > CONTINUATION_TOP:
                            current = None
                        continue
                    elif (re.match(r"(total|mark total)\b", label, re.I)
                          or any(re.match(r"(available|total) marks\b", c) for c in cells)):
                        # the task's sum line ends it; the cover prints it. 2022+ tables
                        # print it as "| | Available marks | 24 |" (9626_m22_ms_02 p6)
                        current = None
                        continue
                    out.append((current, pi, bbox))
        doc.close()
        _ms_task_cache[key] = out
    return _ms_task_cache[key]


def find_answer_spans(ms_path, task):
    """[(page_index, (x0, y0, x1, y1)), ...] - every mark-scheme row of a whole practical
    task, across every page it runs over, in reading order.

    find_answer_range answers a whole task with the rows on ONE page (the page holding
    most of them), so a task whose rows ran onto a second page lost the rest: m25 04
    Task 1 stopped at 1(j), 27 of its 35 marks (ledger P0-PRIOR-015). Contiguous rows on
    a page are merged into one clip; a page break starts a new one."""
    task = re.match(r"\d+", str(task)).group(0)
    clips = []
    prev_ix = None
    for ix, (t, pi, bb) in enumerate(get_ms_task_rows(ms_path)):
        if t != task:
            continue
        if clips and clips[-1][0] == pi and prev_ix == ix - 1:
            x0, y0, x1, y1 = clips[-1][1]
            clips[-1] = (pi, (min(x0, bb[0]), min(y0, bb[1]), max(x1, bb[2]), max(y1, bb[3])))
        else:
            clips.append((pi, tuple(bb)))
        prev_ix = ix
    if not clips:
        raise ValueError(f"answer rows for task {task} not found")
    return clips + ms_appendix_spans(ms_path, task)


# B3-crop-bounds (F-IT-PAGES-OBJECT-NEVER-SHOWN): after the task tables some 2022+
# practical mark schemes print the expected answers themselves - the ERD, the table
# structures, the report - under plain "Task N" headings, with marks callouts beside them
# (9626_m22_ms_02 pp 7-9). Those pages belong to the task the heading names; no crop
# showed them (or one showed them under the wrong task, by continuation).
MS_TASK_HEAD_RE = re.compile(r"^\s*Task\s*(\d{1,2})(?!\d)", re.I)
_ms_appendix_cache: dict[str, list] = {}


def ms_task_headings(page, boxes):
    """[(task, y, page_number), ...]: "Task N" lines printed as headings at the left
    margin, outside every table (a "Task 4 - Webpage" cell inside a table is a row)."""
    out = []
    for blk in page.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            text = "".join(sp["text"] for sp in ln["spans"]).strip()
            m = MS_TASK_HEAD_RE.match(text)
            r = pymupdf.Rect(ln["bbox"])
            if (m and r.x0 < MS_TABLE_MAX_X0 and ln.get("dir", (1, 0))[0] >= 0.99
                    and not any(b.contains(r) or b.intersects(r) for b in boxes)):
                out.append((m.group(1), r.y0, page.number))
    return sorted(out, key=lambda h: h[1])


def ms_appendix_spans(ms_path, task):
    """[(page_index, (x0, y0, x1, y1)), ...] of the sections headed "Task <task>" on the
    pages after the last page that holds task-table rows, each from its heading to the
    next heading (or the end of the page body, running on over following pages). Only
    when the headings name at least two tasks."""
    key = str(ms_path)
    if key not in _ms_appendix_cache:
        rows = get_ms_task_rows(ms_path)
        last = max((pi for t, pi, _bb in rows if t is not None), default=None)
        sections = []
        if last is not None:
            doc = open_upright(ms_path)
            cur = None
            for pi in range(last + 1, doc.page_count):
                page = doc[pi]
                body = ms_page_body(page)
                if body is None:
                    continue
                boxes = [pymupdf.Rect(t.bbox) for t in page.find_tables()]
                heads = ms_task_headings(page, boxes)
                top = body.y0
                for t, y, _p in heads:
                    if cur is not None and y - 4 > top + 5:
                        sections.append((cur, pi, (body.x0, top, body.x1, y - 4)))
                    cur, top = t, max(body.y0, y - 4)
                if cur is not None and body.y1 > top + 5:
                    sections.append((cur, pi, (body.x0, top, body.x1, body.y1)))
            doc.close()
        # headings for one task only do not partition anything (9626_s22_ms_02: one
        # "Task 1" over nine pages of evidence for fourteen tasks): show none of it
        if len({t for t, _pi, _bb in sections}) < 2:
            sections = []
        _ms_appendix_cache[key] = sections
    return [(pi, bb) for t, pi, bb in _ms_appendix_cache[key] if t == str(task)]


# F-IT-ANSWERS-ROWNOTFOUND: practical mark schemes with no row per task. The 2017-2021
# Paper 2 and many Paper 4 mark schemes are free text and screenshots under headings
# ("Task 3", "Q1.", "Evidence 4", "Step 2") rather than a table with a "3" row, so
# find_answer_range raised "answer row N not found" and the unit went into the Questions
# pack but not the Answers pack (228 units, 3 Answers files never written). The answer
# now falls back to whole mark-scheme pages, chosen the way Chapterwise Practical
# chooses them (ms_pages.resolve, verified under F-IT-PRACMS): the task's own pages when
# the headings partition the paper ("split"), else every content page ("whole"), since
# showing extra pages beats pairing a question with the wrong answer.
MS_BOILER_RE = re.compile(r"GENERIC MARKING PRINCIPLE|Generic Marking Principles"
                          r"|These general marking principles", re.I)
MS_FOOT_RE = re.compile(r"UCLES|Page \d+ of \d+")
# one line of the footer itself (the block test above matches a whole footer block)
MS_FOOTER_LINE_RE = re.compile(r"UCLES|Page \d+ of \d+|^\s*©|Cambridge University Press")
MS_RUNNING_HEAD_Y = 46   # CAIE's running head (paper code, PUBLISHED, session) ends here
MS_PAGE_FALLBACKS: list[str] = []


def ms_page_body(page):
    """The part of a mark-scheme page that holds answers: every text line, image and
    drawing below CAIE's running head and above its footer, as one Rect. None for a
    page with nothing on it.

    F-IT-ANSWERS-ROWNOTFOUNDb (CLIP-CUT): an answer may run into or past the footer
    (9626_w17_ms_02 p2 and 9626_w19_ms_02 p4 put their last mark lines level with
    "Page N of M"; 9626_s21_ms_02 p9 runs 13 pt below it). Such a text block used to
    be dropped whole because it ended below the footer, so its lines - and on s21 p9
    the right-hand Marks column - were cut from the pack. A block that crosses the footer
    is now measured line by line: each of its answer lines counts wherever it sits, only
    the footer's own lines do not, and the clip runs past the footer only when an answer
    line does. A page with nothing across its footer is clipped exactly as before."""
    h = page.rect.height
    blocks = page.get_text("blocks")
    foot = [b[1] for b in blocks if b[1] > h - poc.FOOTER_ZONE and MS_FOOT_RE.search(b[4])]
    foot_y = min(foot) if foot else h - 40
    boxes, crossing = [], []
    for b in blocks:
        if not b[4].strip() or re.search(r"dynamicpapers", b[4], re.I):
            continue
        r = pymupdf.Rect(b[:4])
        if r.y0 < MS_RUNNING_HEAD_Y or (r.width <= 0.5 and r.height <= 0.5):
            continue
        if r.y1 <= foot_y + 1:
            boxes.append(r)
        elif r.y0 < foot_y - 1:          # an answer block running into the footer
            crossing.append(r)
    if crossing:
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                lr = pymupdf.Rect(ln["bbox"])
                t = "".join(sp["text"] for sp in ln["spans"])
                if (t.strip() and any(lr.intersects(c) or c.contains(lr) for c in crossing)
                        and lr.y0 >= MS_RUNNING_HEAD_Y
                        and not (lr.y0 > h - poc.FOOTER_ZONE and MS_FOOTER_LINE_RE.search(t))):
                    boxes.append(lr)
    boxes += [r for r in (pymupdf.Rect(im["bbox"]) for im in page.get_image_info())
              if r.y0 >= MS_RUNNING_HEAD_Y and r.y1 <= foot_y + 1]
    boxes += [r for r in (pymupdf.Rect(d["rect"]) for d in page.get_drawings()
                          if d["rect"].width < page.rect.width - 20 or d["rect"].height < h - 20)
              if r.y0 >= MS_RUNNING_HEAD_Y and r.y1 <= foot_y + 1
              and (r.width > 0.5 or r.height > 0.5)]
    if not boxes:
        return None
    x0 = max(0.0, min(r.x0 for r in boxes) - 4)
    x1 = min(page.rect.width, max(r.x1 for r in boxes) + 4)
    y0 = max(MS_RUNNING_HEAD_Y, min(r.y0 for r in boxes) - 4)
    low = max(r.y1 for r in boxes)
    y1 = min(foot_y - 1, low + 4) if low <= foot_y + 1 else min(h, low + 2)
    return pymupdf.Rect(x0, y0, x1, y1) if y1 - y0 > 5 else None


def find_answer_pages(ms_path, qnum_target):
    """([(page_index, (x0, y0, x1, y1)), ...], mode) - the mark-scheme pages answering a
    practical task, one body clip per page.

    The task-to-page map is ms_pages.task_pages_full and the rule is ms_pages.resolve's (mode
    "split" = the task's own pages when the headings partition the paper, else "whole" =
    every content page, also when some content page belongs to no task). Only the
    front matter differs: resolve drops the first two pages
    of any MS over four pages, but 2017-2018 practical mark schemes have no generic
    marking principles page and start answering on page 2 (9626_w17_ms_02 Step 1, the
    data dictionary; 9626_w17_ms_04 Task 1), which was lost. Here the cover (page 1) and
    any page of generic marking principles without a task heading are dropped, and blank
    pages are left out."""
    doc = open_upright(ms_path)
    content = []
    for pi in range(1, doc.page_count):
        text = doc[pi].get_text()
        if MS_BOILER_RE.search(text) and not (ms_pages.HEADING.search(text)
                                              or ms_pages.TASK_HEADING.search(text)):
            continue
        content.append(pi)
    # F-IT-ANSWERS-ROWNOTFOUNDb (SPLIT-MISS): task_pages_full, not task_pages - it also
    # reads "Task 6a", "Task 2b – ...", "Q2, 3 and 4", "Tasks 14–16" and a heading on the
    # line after another, and keeps a page for the previous task when that task's answer
    # runs onto its top. Chapterwise Practical still uses task_pages/resolve.
    tp = ms_pages.task_pages_full(ms_path)
    m = re.match(r"\d+", str(qnum_target))
    hit = sorted(p for p in tp.get(int(m.group()), []) if p in content) if m else []
    bodies = {pi: ms_page_body(doc[pi]) for pi in content}
    # A content page no task heading claims (a table page whose rows are labelled only
    # by a bare task number, e.g. 9626_m23_ms_04 p3-5 and 9626_s22_ms_04 p3-8) may hold
    # this task's answer, so the headings do not partition the paper: show every page.
    claimed = {p for ps in tp.values() for p in ps}
    unclaimed = [pi for pi in content if pi not in claimed and bodies[pi] is not None]
    if (len(tp) < 2 or not hit or unclaimed
            or len(hit) > 0.6 * max(len(content), 1)):
        pages, mode = content, "whole"
    else:
        pages, mode = hit, "split"
    spans = [(pi, tuple(bodies[pi])) for pi in pages if bodies[pi] is not None]
    doc.close()
    if not spans:
        raise ValueError(f"answer row {qnum_target} not found, and no mark-scheme pages "
                         f"for task {qnum_target}")
    return spans, mode


def find_part_crop(qp_path, qnum_target, whole=False, preamble=True):
    """[(page_index, top, bottom), ...] for the target question or sub-part.

    A list because a question can run over several pages, and because a sub-part's
    crop may need to splice in a shared stem range from above it (see narrow_to_part).
    `whole=True` ignores any sub-part suffix and returns the entire question - what the
    practical papers want, since their tasks chain and a lone lettered part is not
    something a candidate could sit. `preamble=False`: see block_spans."""
    blocks = get_qp_blocks(qp_path)
    for b in blocks:
        if b["qnum"] == qnum_target:  # monolithic numbering (some Paper 2/4 practicals: "1a")
            return block_spans(b, preamble)
    main_m = re.match(r"\d+", qnum_target)
    if main_m:
        main_num = main_m.group(0)
        suffix = qnum_target[len(main_num):]
        labels = [g for g in SUBPART_LABEL_RE.findall(suffix) if g]
        for b in blocks:
            if b["qnum"] == main_num:
                if labels and not whole:
                    spans = narrow_to_part(b, labels)
                    if spans:
                        return spans
                    CROP_WARNINGS.append(f"{Path(qp_path).name} {qnum_target}: part label "
                                         "not found, whole question used")
                return block_spans(b, preamble)
    raise ValueError(f"question {qnum_target!r} not found")


# ── write-on: answer space ───────────────────────────────────────────────
# Ported from Papers Toolkit/build_chapterwise_pdfs.py (which was itself ported from this
# file), including its F-WRITEON-GRID fix. The IT Questions.pdf already keeps CAIE's own
# answer space in every crop, so the write-on file uses the same crops; what it adds is
# ruled lines where a crop has no space of its own, and a page flow that keeps a part
# together with its space instead of splitting it across a page turn.
RULED = re.compile(r"^[.·…\s]{12,}$")
# A dot leader with a label in front of it ("Debit .....", "1 .....", "$ .....") is
# answer space too. RULED alone missed it and drew invented lines under a part that
# already had its labelled lines. 20 dots in a row never occur in question prose.
LEADER = re.compile(r"(?:[.·…]\s?){20,}")
MARKS_RE = re.compile(r"\[(\d{1,2})\]")
# A part that tells the candidate to write on a printed figure ("Complete the flowchart",
# "Complete the table") answers on the figure itself.
FILL_IN_RE = re.compile(r"^(?:\d{1,2}\s+)?(?:\((?:[a-h]|[ivx]{1,4})\)\s*)*"
                        r"(?:Complete|Draw|Label|Plot|Sketch|Fill in)\b")
RULE_GAP = 26      # CAIE's own answer-line pitch
MIN_SPILL_H = 150  # an item taller than a sheet still needs this much room to start


def _rules(page, top, bottom):
    """CAIE's solid horizontal and vertical rules inside the band, as zero-width or
    zero-height Rects. Boxes are split into their four edges; dashed and dotted
    strokes and anything the size of the whole sheet are left out."""
    out = []
    for dr in page.get_drawings():
        r = dr["rect"]
        if r.y1 < top - 1 or r.y0 > bottom + 1:
            continue
        if dr.get("dashes") not in (None, "[] 0", "[] 0.0"):
            continue
        if r.width > 560 and r.height > 700:
            continue
        for it in dr["items"]:
            if it[0] == "l":
                p, q = it[1], it[2]
                if abs(p.y - q.y) < 1 and abs(p.x - q.x) > 15:
                    out.append(pymupdf.Rect(min(p.x, q.x), p.y, max(p.x, q.x), p.y))
                elif abs(p.x - q.x) < 1 and abs(p.y - q.y) > 10:
                    out.append(pymupdf.Rect(p.x, min(p.y, q.y), p.x, max(p.y, q.y)))
            elif it[0] == "re":
                rc = pymupdf.Rect(it[1])
                if rc.height <= 2 and rc.width > 15:          # a rule drawn as a thin fill
                    y = (rc.y0 + rc.y1) / 2
                    out.append(pymupdf.Rect(rc.x0, y, rc.x1, y))
                elif rc.width <= 2 and rc.height > 10:
                    x = (rc.x0 + rc.x1) / 2
                    out.append(pymupdf.Rect(x, rc.y0, x, rc.y1))
                elif rc.width > 15 and rc.height > 10 and dr.get("color") is not None:
                    out += [pymupdf.Rect(rc.x0, rc.y0, rc.x1, rc.y0),   # stroked box
                            pymupdf.Rect(rc.x0, rc.y1, rc.x1, rc.y1),
                            pymupdf.Rect(rc.x0, rc.y0, rc.x0, rc.y1),
                            pymupdf.Rect(rc.x1, rc.y0, rc.x1, rc.y1)]
    return [s for s in out if s.y0 >= top - 2 and s.y1 <= bottom + 2]


def _grids(rules, tol=3):
    """Rules that touch one another, grouped: one (bbox, members) per grid or box.
    Coordinates are compared by hand - a rule is an empty Rect and pymupdf's
    intersects() is always False for one."""
    parent = list(range(len(rules)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i, a in enumerate(rules):
        for j in range(i):
            b = rules[j]
            if (a.x0 - tol <= b.x1 and b.x0 - tol <= a.x1
                    and a.y0 - tol <= b.y1 and b.y0 - tol <= a.y1):
                parent[root(i)] = root(j)
    groups = {}
    for i, r in enumerate(rules):
        groups.setdefault(root(i), []).append(r)
    return [(pymupdf.Rect(min(r.x0 for r in m), min(r.y0 for r in m),
                          max(r.x1 for r in m), max(r.y1 for r in m)), m)
            for m in groups.values()]


def drawn_answer_space(page, top, bottom):
    """Height of the writing space CAIE draws in this band instead of dot leaders: the
    rows of a ruled answer grid (a table with its headings printed and its cells left
    blank, a column of tick boxes) or a box.

    A row counts when it is empty, has a text-free gap of 30pt (a box with only its
    caption in it), or has an empty cell. A data table printed as part of the question
    has something in nearly every cell, so a grid only counts when its empty cells make
    up a quarter of its area."""
    words = page.get_text("words")
    total = 0.0
    for box, members in _grids(_rules(page, top, bottom)):
        hs = sorted({round(m.y0, 1) for m in members if m.height < 0.5})
        if box.height < 12 or box.width < 30 or len(hs) < 2:
            continue
        inside = [w for w in words if box.x0 - 1 <= (w[0] + w[2]) / 2 <= box.x1 + 1
                  and box.y0 - 1 <= (w[1] + w[3]) / 2 <= box.y1 + 1]
        empty_area = rows_h = 0.0
        n_empty = 0
        for a, b in zip(hs, hs[1:]):
            if b - a < 12:
                continue
            row = [w for w in inside if a < (w[1] + w[3]) / 2 < b]
            gap, cur = 0.0, a
            for y0, y1 in sorted((w[1], w[3]) for w in row):
                gap, cur = max(gap, y0 - cur), max(cur, y1)
            gap = max(gap, b - cur)
            if not row or gap >= 30:
                empty_area += (b - a) * box.width
                rows_h += b - a
                n_empty += 2
                continue
            xs = sorted({box.x0, box.x1} | {m.x0 for m in members if m.width < 0.5
                                            and m.y0 <= a + 2 and m.y1 >= b - 2})
            blank = [(l, r) for l, r in zip(xs, xs[1:]) if r - l > 20
                     and not any(l < (w[0] + w[2]) / 2 < r for w in row)]
            if blank:
                empty_area += sum(r - l for l, r in blank) * (b - a)
                rows_h += b - a
                n_empty += len(blank)
        if n_empty >= 2 and empty_area >= 0.25 * box.width * box.height:
            total += rows_h
    return total


def tick_grid(page, top, bottom):
    """True where the band holds a ruled table with a column of empty cells beside
    filled ones - the tick-box tables of 2017-2019 Paper 1 ("Tick the four most
    accurate statements"). The tick column is narrow and the statements fill most of
    the area, so drawn_answer_space's quarter-of-the-area test does not see it, and
    drawing lines under a tick table would invent space the paper never had."""
    words = page.get_text("words")
    for box, members in _grids(_rules(page, top, bottom)):
        hs = sorted({round(m.y0, 1) for m in members if m.height < 0.5})
        if box.width < 100 or len(hs) < 3:
            continue
        empties = 0
        for a, b in zip(hs, hs[1:]):
            if b - a < 10:
                continue
            row = [w for w in words if a < (w[1] + w[3]) / 2 < b
                   and box.x0 < (w[0] + w[2]) / 2 < box.x1]
            xs = sorted({box.x0, box.x1} | {m.x0 for m in members if m.width < 0.5
                                            and m.y0 <= a + 2 and m.y1 >= b - 2})
            if row and any(r - l >= 12 and not any(l < (w[0] + w[2]) / 2 < r for w in row)
                           for l, r in zip(xs, xs[1:])):
                empties += 1
        if empties >= 2:
            return True
    return False


def fill_in_figure(page, top, bottom):
    """True where the part says to complete / draw on a figure printed in the band:
    the figure is the answer space."""
    band = pymupdf.Rect(0, top, page.rect.width, bottom)
    said = any(FILL_IN_RE.match(" ".join(line.split()))
               for line in page.get_text("text", clip=band).splitlines())
    if not said:
        return False
    return any(r.y1 > top and r.y0 < bottom and r.width >= 60 and r.height >= 40
               and r.height < 700 for r in page.cluster_drawings())


def answer_lines_for(page, top, bottom):
    """How many ruled lines to draw under this crop: 0 for none, None where CAIE prints
    its own answer space in the band - dot leaders, a ruled answer grid, box or tick
    table, or a figure the part says to complete. Where CAIE prints its own space it is
    used as it is; lines are only invented for a crop that has none at all.

    1.7 lines per mark is the ratio CAIE itself uses on its essay papers, at its own
    26pt pitch. Capped at 34 so a long question does not run to three sheets."""
    marks = 0
    for blk in page.get_text("dict")["blocks"]:
        for line in blk.get("lines", []):
            if line["bbox"][3] <= top or line["bbox"][1] >= bottom:
                continue
            text = "".join(sp["text"] for sp in line["spans"]).strip()
            if RULED.match(text) or LEADER.search(text):
                return None       # the paper supplies its own space
            m = MARKS_RE.search(text)
            if m:
                marks = max(marks, int(m.group(1)))
    if (drawn_answer_space(page, top, bottom) or tick_grid(page, top, bottom)
            or fill_in_figure(page, top, bottom)):
        return None
    return min(34, max(3, round(1.7 * marks))) if marks else 0


def trailing_blank(page, bottom):
    """Height of the empty paper CAIE leaves below `bottom` on this page, down to the
    next line of text, the next image or the page footer.

    Some parts have no dots and no grid at all: "Draw your program flowchart below."
    followed by a blank page. The crop stops at the last line of text, so the space a
    candidate draws in never reached the pack, and ruled lines under a flowchart
    question are the wrong kind of space anyway."""
    ph = page.rect.height
    below, foot = [], []
    for blk in page.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            x0, t, _x1, b = ln["bbox"]
            text = "".join(sp["text"] for sp in ln["spans"]).strip()
            if not text or ln.get("dir", (1, 0))[0] < 0.99 or b - t > 60:
                continue
            if b > ph - poc.FOOTER_ZONE and (FOOTER_TEXT_RE.search(text) or is_noise(text, t, b)):
                foot.append(t)
            elif t > bottom + 1 and x0 >= 45 and not is_noise(text, t, b):
                below.append(t)
    below += [im["bbox"][1] for im in page.get_image_info()
              if im["bbox"][1] > bottom + 1 and im["bbox"][3] - im["bbox"][1] >= 5]
    end = min([min(foot) if foot else ph - poc.FOOTER_ZONE / 3] + below)
    return max(0.0, end - bottom - 6)


def widen_clip(page, clip):
    """`clip` grown sideways over any ruled box or table that pokes out of it.

    The crop is cut at the output margins (50-545pt) but CAIE draws some answer boxes
    from 48 to 548pt, so the box lost both of its sides and a student could not see
    where the space ended. Narrow tables count too (9626_s20_qp_11 Q5 prints four 75pt
    tables edge to edge), but not the corner registration marks in the head and foot
    margins, and never past 40/560pt (the "DO NOT WRITE IN THIS MARGIN" strip)."""
    x0, x1 = clip.x0, clip.x1
    ph = page.rect.height
    for d in page.get_drawings():
        r = d["rect"]
        if r.y1 < poc.HEADER_ZONE or r.y0 > ph - 55:
            continue                       # corner marks, barcodes
        if r.width > 20 and r.y1 > clip.y0 and r.y0 < clip.y1 and r.height < 700:
            x0, x1 = min(x0, max(r.x0 - 1.5, 40)), max(x1, min(r.x1 + 1.5, 560))
    # Up and down too, a little: the crop ends 10pt under the last line of text, and
    # where that text sits in the last box of a flowchart the box lost its bottom edge.
    y0, y1 = clip.y0, clip.y1
    for r in page.cluster_drawings():
        if r.width < 100 or r.height > 700:
            continue
        if r.y0 < y1 < r.y1 and r.y1 - y1 <= 40:
            y1 = min(r.y1 + 2, page.rect.height - 50)
        if r.y0 < y0 < r.y1 and y0 - r.y0 <= 20:
            y0 = max(r.y0 - 2, poc.HEADER_ZONE)
    return pymupdf.Rect(x0, y0, x1, y1)


WORKING_RE = re.compile(r"\b(?:space|area|box)\b.*\bbelow\b|\bworking\b|\bbelow\s*[.:]?$", re.I)


def keep_working_space(page, clip):
    """`clip` grown down over the blank paper CAIE leaves under "You can use the space
    below for any working you need." (or "Draw ... below.").

    The crop stops 10pt under the last line of text, so where that line is the
    invitation itself the space it invites the candidate to use was cut off: every
    spreadsheet formula question on 2018-2019 Paper 1 lost its working area. Only when
    the last line of the clip says so, so the white space CAIE leaves at the foot of an
    ordinary page is not copied in."""
    last = None
    for blk in page.get_text("dict")["blocks"]:
        for ln in blk.get("lines", []):
            t, b = ln["bbox"][1], ln["bbox"][3]
            text = "".join(sp["text"] for sp in ln["spans"]).strip()
            if (text and ln.get("dir", (1, 0))[0] >= 0.99 and b - t <= 60
                    and t < clip.y1 and b > clip.y0 and not is_noise(text, t, b)
                    and (last is None or b > last[0])):
                last = (b, text)
    if last is None or not WORKING_RE.search(last[1]):
        return clip
    blank = trailing_blank(page, clip.y1)
    if blank < 30:
        return clip
    return pymupdf.Rect(clip.x0, clip.y0, clip.x1, clip.y1 + blank)


def widen_for_cut_text(page, clip):
    """F-IT-P1-QA (fix 3): `clip` grown sideways where printed text runs past its left or
    right edge, so a table set wider than the 50-545pt crop keeps its outer columns
    (9626_s21_qp_12 Q5 printed "lonth"/"De"/"12" for Month/Dec/1220; 9626_s19_qp_12 Q11
    lost "€7.99" to "€7."). Only a word more than 3pt past the edge triggers it - CAIE's
    own right-justified text ends at 545-546pt - and then the clip takes in every word
    and table rule in the band. Words in the outer "DO NOT WRITE IN THIS MARGIN" strips
    are ignored. PageFlow scales the wider item down to the usable width."""
    pw = page.rect.width
    words = [w for w in page.get_text("words")
             if clip.y0 <= (w[1] + w[3]) / 2 <= clip.y1 and w[2] > 35 and w[0] < pw - 35]
    # B3-crop-bounds (F-IT-PAGES-CLIP-OBJECT): a picture set wider than the crop too -
    # 9626_w21_qp_04 Q4 prints two 128pt screenshots at x 37-165 and 433-561, and the
    # 50-545pt crop cut 10-12% off each. A picture counts when most of its height is in
    # the band and it is not a margin speck (the strips outside 35pt carry no pictures).
    imgs = []
    for im in page.get_image_info():
        r = pymupdf.Rect(im["bbox"])
        if r.width < 20 or r.height < 20 or r.x1 <= 60 or r.x0 >= pw - 60:
            continue
        if min(r.y1, clip.y1) - max(r.y0, clip.y0) >= 0.5 * r.height:
            imgs.append((max(r.x0, 35), r.y0, min(r.x1, pw - 35), r.y1))
    if not any(w[0] < clip.x0 - 3 or w[2] > clip.x1 + 3 for w in words + imgs):
        return clip
    x0 = min([clip.x0] + [w[0] for w in words + imgs])
    x1 = max([clip.x1] + [w[2] for w in words + imgs])
    for d in page.get_drawings():
        r = d["rect"]
        if (r.width > 20 and r.height < 700 and r.y1 > clip.y0 and r.y0 < clip.y1
                and r.y1 > poc.HEADER_ZONE and r.y0 < page.rect.height - 55):
            x0, x1 = min(x0, r.x0), max(x1, r.x1)
    return pymupdf.Rect(max(x0 - 2, 25), clip.y0, min(x1 + 2, pw - 25), clip.y1)


def _is_space_line(text):
    return bool(RULED.match(text) or LEADER.search(text))


class WriteOnFlow(poc.PageFlow):
    """PageFlow for the write-on file. Same items, same citations, same order as the
    Questions file; the differences are all about where a page turn may fall.

    - An item that fits on a sheet of its own is never split: it goes whole onto a
      fresh sheet (the Questions flow splits anything that leaves a third behind,
      which put a part's text on one sheet and its answer lines on the next).
    - An item taller than a sheet turns the page where the original paper did; a
      single source page taller than a sheet is cut at a gap that no text, drawing
      or image crosses, preferring one just above a line of question text, so a
      part's lines stay with it and a page never opens on loose dots.
    - `tail_lines` draws ruled lines under an item whose crop has no space of its own,
      counted in the fit decision so the item and its lines stay on one sheet."""

    def _cuts(self, src_doc, page_index, clip):
        """[(y, good)] split points in `clip`: gaps that no text line, drawing or image
        crosses, so a cut never runs through a table, a flowchart or a box. `good` =
        what starts below the gap is not a row of answer dots. Where a clip has no such
        gap at all (one figure filling it), plain gaps between text lines are used."""
        page = src_doc[page_index]
        rows = []
        for blk in page.get_text("dict")["blocks"]:
            for ln in blk.get("lines", []):
                t, b = ln["bbox"][1], ln["bbox"][3]
                if b <= clip.y0 or t >= clip.y1 or b - t > 60:
                    continue
                text = "".join(sp["text"] for sp in ln["spans"]).strip()
                if text:
                    rows.append((max(t, clip.y0), min(b, clip.y1), _is_space_line(text)))
        ink = [(max(r.y0, clip.y0), min(r.y1, clip.y1), False)
               for r in [d["rect"] for d in page.get_drawings()]
               + [pymupdf.Rect(im["bbox"]) for im in page.get_image_info()]
               if r.y1 > clip.y0 and r.y0 < clip.y1 and r.x1 > clip.x0 and r.x0 < clip.x1
               and r.height < 700]

        def gaps(items):
            out, bottom = [], None
            for t, b, dots in sorted(items):
                if bottom is not None and t > bottom + 0.5:
                    out.append(((bottom + t) / 2, not dots))
                bottom = b if bottom is None else max(bottom, b)
            return out
        return gaps(rows + ink) or gaps(rows)

    def place(self, src_doc, page_index, clips, label, qnum, tail_lines=0, box_h=0):
        """`box_h` draws an empty framed box that tall under the item instead: the
        original's own blank drawing space, for a part that has no lines to copy.

        Page turns fall where the original paper turned its page whenever possible:
        each source-page clip that fits on a fresh sheet is kept whole, and only a
        clip taller than a sheet is cut (see _cuts)."""
        if isinstance(clips, pymupdf.Rect):
            clips = [clips]
        clips = [c if isinstance(c, tuple) else (page_index, c) for c in clips]
        if self.page is None:
            self._new_page()
        header_h = poc.CITE_H + poc.CONTENT_PAD
        min_useful = header_h + 30
        fresh_h = poc.PAGE_H - poc.BOTTOM_MARGIN - poc.TOP_MARGIN - header_h
        k = min(1.0, poc.USABLE_W / max(c.width for _, c in clips))
        # a source page's content is a few points taller than an output sheet holds;
        # shrink the item a little rather than cut a sliver off its foot
        tallest = max(c.height for _, c in clips)
        if fresh_h < tallest * k <= 1.1 * fresh_h:
            k = fresh_h / tallest
        x0 = poc.LEFT_MARGIN if k < 1 else None
        box_h = min(box_h, fresh_h - 12)
        total_h = (sum(c.height for _, c in clips) * k + tail_lines * RULE_GAP
                   + (box_h + 6 if box_h else 0))
        page_end = poc.PAGE_H - poc.BOTTOM_MARGIN
        placed_any = False
        need_header = True
        for src_page, clip in clips:
            remaining_top, bottom = clip.y0, clip.y1
            cut_points = None
            clip_start = True
            while remaining_top < bottom - 0.5:
                available = page_end - self.cursor
                reserve = min_useful if need_header else 20
                fitting = available - (header_h if need_header else 0)
                clip_h = (bottom - remaining_top) * k
                if available < reserve:
                    self._new_page()
                    need_header = True
                elif not placed_any and fitting < total_h and self.cursor > poc.TOP_MARGIN:
                    # the item does not fit in what is left of this sheet: start it on a
                    # fresh one - whole if it fits there, else at least lined up with
                    # the original's own page turns
                    self._new_page()
                    need_header = True
                elif (placed_any and clip_start and fitting < clip_h
                      and (clip_h <= fresh_h or fitting < MIN_SPILL_H)):
                    # a later clip (the part's next source page): whole on a fresh
                    # sheet where it fits on one, never started as a sliver
                    self._new_page()
                    need_header = True
                y = self.cursor
                if need_header:
                    poc.draw_item_citation(self.page, y, label, qnum, continued=placed_any)
                    y += poc.CITE_H + poc.CONTENT_PAD
                    need_header = False
                slice_h = min((page_end - y) / k, bottom - remaining_top)
                slice_end = remaining_top + slice_h
                if slice_end < bottom - 0.5:  # forced split - snap to a real gap
                    if cut_points is None:
                        cut_points = self._cuts(src_doc, src_page, clip)
                    cands = [c for c in cut_points if remaining_top < c[0] <= slice_end]
                    good = [c for c, ok in cands if ok]
                    span = slice_end - remaining_top
                    if good and good[-1] - remaining_top >= 0.4 * span:
                        slice_end = good[-1]
                    elif cands:
                        slice_end = cands[-1][0]
                    slice_h = slice_end - remaining_top
                src_slice = pymupdf.Rect(clip.x0, remaining_top, clip.x1,
                                         remaining_top + slice_h)
                left = clip.x0 if x0 is None else x0
                target = pymupdf.Rect(left, y, left + clip.width * k, y + slice_h * k)
                sub = poc.redacted_copy(src_doc, src_page, src_slice)
                self.page.show_pdf_page(target, sub, 0, clip=src_slice)
                sub.close()
                remaining_top += slice_h
                self.cursor = y + slice_h * k + poc.ITEM_GAP
                placed_any = True
                clip_start = False
                if remaining_top < bottom - 0.5:
                    self._new_page()
                    need_header = True
        if tail_lines:
            self.cursor -= poc.ITEM_GAP   # the rules are part of the item, not the next one
            for _ in range(tail_lines):
                if page_end - self.cursor < RULE_GAP:
                    self._new_page()
                    poc.draw_item_citation(self.page, self.cursor, label, qnum, continued=True)
                    self.cursor += poc.CITE_H + poc.CONTENT_PAD
                self.cursor += RULE_GAP
                self.page.draw_line((poc.LEFT_MARGIN, self.cursor),
                                    (poc.RIGHT_MARGIN, self.cursor),
                                    color=(0.32, 0.34, 0.38), width=0.9, dashes="[1 2] 0")
            self.cursor += poc.ITEM_GAP
        if box_h:
            self.cursor -= poc.ITEM_GAP
            if page_end - self.cursor < box_h + 6:      # the box is never split
                self._new_page()
                poc.draw_item_citation(self.page, self.cursor, label, qnum, continued=True)
                self.cursor += poc.CITE_H + poc.CONTENT_PAD
            top = self.cursor + 6
            self.page.draw_rect(pymupdf.Rect(poc.LEFT_MARGIN, top, poc.RIGHT_MARGIN,
                                             top + box_h),
                                color=(0.32, 0.34, 0.38), width=0.8)
            self.cursor = top + box_h + poc.ITEM_GAP


# ── build ──────────────────────────────────────────────────────────────
def build_chapter(paper_dir_name, chapter_path, report):
    entries = parse_chapter_md(chapter_path)
    pdf_dir = PDF_ROOT / paper_dir_name
    out_dir = OUT_ROOT / paper_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = chapter_path.stem

    q_doc, a_doc = pymupdf.open(), pymupdf.open()
    q_flow, a_flow = poc.PageFlow(q_doc), poc.PageFlow(a_doc)
    # The write-on file: the same crops as the Questions file, CAIE's answer space and
    # all, laid out so a part stays on one sheet with its space (see WriteOnFlow).
    w_flow = (WriteOnFlow(pymupdf.open())
              if paper_dir_name.split()[-1] not in NO_WRITE_ON else None)
    # A question that tests two subtopics of one chapter is listed under both in the
    # .md, which is right for reading and wrong for printing. Ten such entries exist
    # across the 9626 corpus and each was being cropped and placed twice.
    seen = set()
    entries = [e for e in entries
               if not (("qp" in e) and ((e["qp"], e["qnum"]) in seen
                                        or seen.add((e["qp"], e["qnum"]))))]
    ok = 0
    COMPACT_EVERY = 15  # keeps memory bounded through very large chapters (200+ entries)
    for n, e in enumerate(entries, 1):
        try:
            qp_path, ms_path = pdf_dir / e["qp"], pdf_dir / e["ms"]

            spans = find_part_crop(qp_path, e["qnum"])
            src_q = open_upright(qp_path)
            # F-IT-P1-QA (fix 3): widen a crop where a table runs past the margins
            clips = [(pi, widen_for_cut_text(src_q[pi], pymupdf.Rect(
                         poc.LEFT_MARGIN, top, poc.RIGHT_MARGIN, bottom)))
                     for pi, top, bottom in spans]
            q_flow.place(src_q, spans[0][0], clips, e["label"], e["qnum"])
            if w_flow is not None:
                # One page of a part can carry CAIE's own space while another carries
                # none (a stem slice): any own space on any page means no added lines.
                need = [answer_lines_for(src_q[pi], top, bottom) for pi, top, bottom in spans]
                tail = 0 if any(n is None for n in need) else max(need, default=0)
                box = 0.0
                if tail:
                    # blank paper left to draw on (a flowchart) is copied as a box of
                    # the same height, not turned into ruled lines
                    box = sum(trailing_blank(src_q[pi], bottom) for pi, _t, bottom in spans)
                    if box >= 100:
                        tail = 0
                    else:
                        box = 0.0
                    WRITE_ON_TAILS.append(f"{paper_dir_name}/{stem}: {e['qp']} {e['qnum']} "
                                          + (f"+{tail} lines" if tail else f"box {box:.0f}pt"))
                w_clips = [(pi, widen_clip(src_q[pi], c)) for pi, c in clips]
                if not box and not tail:
                    w_clips = [(pi, keep_working_space(src_q[pi], c)) for pi, c in w_clips]
                w_flow.place(src_q, spans[0][0], w_clips, e["label"], e["qnum"],
                             tail_lines=tail, box_h=box)
            src_q.close()

            # F-IT-P1-QA (fix 1): every row of the answer on every MS page, not one page.
            # Theory papers only; the practicals (Papers 2 and 4) keep the old one-page crop.
            ms_header = poc.draw_ms_header
            if paper_dir_name.split()[-1] in {"2", "4"}:
                try:
                    page_i, row_bbox = find_answer_range(ms_path, e["qnum"])
                    ms_spans = [(page_i, row_bbox)]
                except ValueError:
                    # F-IT-ANSWERS-ROWNOTFOUND: no row per task - whole MS pages instead.
                    # No reconstructed "Question | Answer | Marks" header: these pages
                    # are not that table.
                    ms_spans, mode = find_answer_pages(ms_path, e["qnum"])
                    ms_header = None
                    MS_PAGE_FALLBACKS.append(
                        f"{paper_dir_name}/{stem}: {e['ms']} Q{e['qnum']} -> {mode} pages "
                        f"{[pi + 1 for pi, _bb in ms_spans]}")
            else:
                ms_spans = find_answer_spans_theory(ms_path, e["qnum"])
            src_a = open_upright(ms_path)
            a_flow.place(src_a, ms_spans[0][0], [(pi, pymupdf.Rect(*bb)) for pi, bb in ms_spans],
                         e["label"], e["qnum"], header_fn=ms_header,
                         split_each_clip=True)
            src_a.close()
            ok += 1
        except Exception as exc:
            report.append(f"- SKIP `{paper_dir_name}/{stem}` Q{e['qnum']} ({e['label']}): {exc}")

        if n % COMPACT_EVERY == 0:
            q_flow.compact()
            a_flow.compact()
            if w_flow is not None:
                w_flow.compact()

    # compact() may have swapped in a new Document for q_flow/a_flow.out_doc -
    # always save through the flow, never the original q_doc/a_doc handle.
    save_kwargs = {"garbage": 4, "deflate": True, "clean": True}
    if q_flow.out_doc.page_count:
        q_flow.out_doc.save(out_dir / f"{stem} - Questions.pdf", **save_kwargs)
    if a_flow.out_doc.page_count:
        a_flow.out_doc.save(out_dir / f"{stem} - Answers.pdf", **save_kwargs)
    if w_flow is not None and w_flow.out_doc.page_count:
        w_flow.out_doc.save(out_dir / f"{stem} - Questions (write-on).pdf", **save_kwargs)
        w_flow.out_doc.close()
    q_flow.out_doc.close()
    a_flow.out_doc.close()
    return ok, len(entries)


def main():
    global OUT_ROOT
    only = sys.argv[1:]
    report_path = REPORT_PATH
    if "--out" in only:
        i = only.index("--out")
        OUT_ROOT = Path(only[i + 1]).resolve()
        report_path = OUT_ROOT / REPORT_PATH.name
        del only[i:i + 2]
    if only:
        report_path = report_path.with_name(f"{REPORT_PATH.stem} ({', '.join(only)}).md")
    report = ["# Chapterwise PDF build report\n"]
    totals = [0, 0]
    for paper_dir in sorted(BY_TOPIC.iterdir()):
        if not paper_dir.is_dir() or (only and paper_dir.name not in only):
            continue
        report.append(f"\n## {paper_dir.name}\n")
        for chapter_path in sorted(paper_dir.glob("*.md")):
            ok, total = build_chapter(paper_dir.name, chapter_path, report)
            totals[0] += ok
            totals[1] += total
            report.append(f"- {chapter_path.stem}: {ok}/{total} placed")

    if CROP_WARNINGS:
        report.append("\n## Part crops that fell back to the whole question\n")
        report += [f"- {w}" for w in sorted(set(CROP_WARNINGS))]
    if MS_PAGE_FALLBACKS:
        report.append("\n## Practical answers given as whole mark-scheme pages "
                      "(no row per task; split = the task's own pages, whole = every page)\n")
        report += [f"- {w}" for w in MS_PAGE_FALLBACKS]
    if WRITE_ON_TAILS:
        report.append("\n## Write-on parts with no printed answer space (ruled lines added)\n")
        report += [f"- {w}" for w in WRITE_ON_TAILS]
    report.insert(1, f"\n**{totals[0]}/{totals[1]} entries placed overall.**\n")
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text("\n".join(report))
    print(f"{totals[0]}/{totals[1]} entries placed. Report: {report_path}")


# The per-source-PDF scans above are most of a build and come out the same every run,
# so they are kept on disk too (pack_cache.py; PACK_CACHE=0 turns it off). The cache is
# keyed on the code of these three modules: a module that one of the hooked functions
# comes to call must be added here, or a fix to it would be hidden by stale results.
# Hook only functions of one source PDF - never anything that reads tags or By Topic.
import pack_cache  # noqa: E402

_disk = pack_cache.hook("it", __file__, poc.__file__, poc.sp.__file__)
open_upright = _disk(open_upright, _upright_cache)
get_qp_blocks = _disk(get_qp_blocks, _qp_block_cache)
get_ms_rows = _disk(get_ms_rows, _ms_row_cache)
get_ms_part_rows = _disk(get_ms_part_rows, _ms_part_cache)


if __name__ == "__main__":
    main()
