"""
Proof of concept: pull single questions + their mark-scheme rows straight out
of the original PDFs (as native vector clips, not rasterised images) and
assemble them into a chapter booklet that still looks like a CAIE paper.

Three source PDFs are hardcoded below (9626_s17_qp_13 Q3, 9626_s24_qp_11 Q2,
9626_s18_qp_13 Q4) - all already confirmed as "1 Data processing and
information" in By Topic/Paper 1/1 Data processing and information.md. This
is a proof of concept for ONE chapter, not the full pipeline - see the
bottom of this file for what's not handled yet.

USAGE: scripts/venv/bin/python3 scripts/poc_chapter_pdf.py
OUTPUT: Reports/poc_chapter_questions.pdf, Reports/poc_chapter_answers.pdf
"""

import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
import split_papers as sp

PDF_DIR = Path("PDFs/Paper 1")
OUT_DIR = Path("Reports")

PAGE_W, PAGE_H = 595, 842  # fixed A4 - every output page prints as A4, whatever the content height
LEFT_MARGIN = 50
RIGHT_MARGIN = 545
USABLE_W = RIGHT_MARGIN - LEFT_MARGIN
TOP_PAD = 6      # pt above the question number, kept from the source crop
BOTTOM_PAD = 10  # pt below the last content line
TOP_MARGIN = 40
BOTTOM_MARGIN = 40
CITE_H = 18      # per-item citation line, now printed above EACH item instead of once per page
CONTENT_PAD = 10 # gap between the citation rule and the actual content below it
ITEM_GAP = 20    # blank space between one item's content and the next item's citation
MIN_SLICE = 12  # pt: the shortest slice of a split item worth leaving on a sheet
MIN_SPLIT_FRACTION = 1 / 3  # a page break is only allowed to leave this much (or more) of the
                             # content behind before spilling - otherwise a single leftover line
                             # before a page flip is more annoying than just starting fresh

FOOTER_ZONE = 60   # bottom margin height where CAIE prints copyright/paper code
HEADER_ZONE = 55   # top margin height where CAIE prints the watermark / decoy page number

# (qp filename, ms filename, question number, human label for the citation)
EXAMPLES = [
    ("9626_s17_qp_13.pdf", "9626_s17_ms_13.pdf", "3", "9626/13 May/June 2017"),
    ("9626_s24_qp_11.pdf", "9626_s24_ms_11.pdf", "2", "9626/11 May/June 2024"),
    ("9626_s18_qp_13.pdf", "9626_s18_ms_13.pdf", "4", "9626/13 May/June 2018"),
]


def get_lines(page, require_bold):
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            top, bottom = line["bbox"][1], line["bbox"][3]
            qnum = sp.is_question_start_line(text, spans[0], require_bold) if spans else None
            out.append((text, top, bottom, qnum))
    return out


def find_question_crop(doc, qnum_target):
    """(page_index, top, bottom) tightly bounding qnum_target's own content,
    skipping header/footer boilerplate on both sides. Assumes the question
    doesn't cross a page (true for every full-numbered question checked)."""
    require_bold = sp.doc_has_named_bold_font(doc)
    current = None
    for pi, page in enumerate(doc):
        ph = page.rect.height
        for text, top, bottom, qnum in get_lines(page, require_bold):
            boiler = top < HEADER_ZONE or bottom > ph - FOOTER_ZONE
            if boiler:
                continue
            if qnum is not None and sp.continues_sequence(qnum, current["qnum"] if current else None):
                if current and current["qnum"] == qnum_target:
                    return current["page"], current["top"], current["bottom"]
                current = {"qnum": qnum, "page": pi, "top": top - TOP_PAD, "bottom": bottom + BOTTOM_PAD}
            elif current is not None and pi == current["page"]:
                current["bottom"] = max(current["bottom"], bottom + BOTTOM_PAD)
    if current and current["qnum"] == qnum_target:
        return current["page"], current["top"], current["bottom"]
    raise ValueError(f"question {qnum_target} not found")


def find_answer_row(ms_doc, qnum_target):
    """(page_index, row_rect) for the mark scheme's data row matching
    qnum_target, using pymupdf's own table-row boundaries so the cut falls
    exactly on the grid line - no guessing at pixel offsets."""
    for pi, page in enumerate(ms_doc):
        for table in page.find_tables():
            rows = table.extract()
            for i, row in enumerate(rows):
                if row and row[0] and str(row[0]).strip() == qnum_target:
                    return pi, table.rows[i].bbox
    raise ValueError(f"answer row {qnum_target} not found")


def draw_item_citation(out_page, y, label, qnum, continued=False):
    out_page.draw_line((LEFT_MARGIN, y + CITE_H - 4), (RIGHT_MARGIN, y + CITE_H - 4),
                        color=(0.6, 0.6, 0.6), width=0.6)
    suffix = "  (continued)" if continued else ""
    # qnum=None: the item is not a question (a scenario/rubric preamble), so naming one
    # would be a lie - the label carries the whole citation itself.
    head = f"{label}  •  Question {qnum}" if qnum is not None else label
    out_page.insert_text((LEFT_MARGIN, y + 10), f"{head}{suffix}",
                          fontname="helv", fontsize=9, color=(0.35, 0.35, 0.35))


def safe_cut_points(src_doc, page_index, clip, objects=False):
    """y-coordinates inside `clip` that fall between two text lines - a
    forced page split has to land on one of these, not an arbitrary pixel
    offset, or it slices straight through the middle of a line of text.

    objects=True (B3-crop-bounds, F-IT-PAGES-CLIP-OBJECT): the gap must not cross a
    picture or a drawn figure either. Text lines alone left the whole height of a
    screenshot "safe" (9626_w24_qp_04 Q4: the split fell 61pt into a 210pt picture), and
    a flowchart's labels have gaps between them. Tables are not objects here: a cut
    between two of their rows is where a long table should turn the page."""
    page = src_doc[page_index]
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            top, bottom = line["bbox"][1], line["bbox"][3]
            if bottom <= clip.y0 or top >= clip.y1:
                continue
            spans.append((max(top, clip.y0), min(bottom, clip.y1)))
    if objects:
        spans += [(max(r.y0, clip.y0), min(r.y1, clip.y1)) for r in page_objects(page, clip)]
    spans.sort()
    cuts = []
    if not objects:
        for (_, prev_bottom), (next_top, _) in zip(spans, spans[1:]):
            if next_top > prev_bottom + 0.5:
                cuts.append((prev_bottom + next_top) / 2)
        return cuts
    # an object spans many text lines: a gap counts only below everything above it
    bottom_so_far = None
    for top, bottom in spans:
        if bottom_so_far is not None and top > bottom_so_far + 0.5:
            cuts.append((bottom_so_far + top) / 2)
        bottom_so_far = bottom if bottom_so_far is None else max(bottom_so_far, bottom)
    return cuts


def page_objects(page, clip):
    """Pictures and drawn figures (not tables) that reach into `clip`: raster images and
    vector drawing clusters at least 20pt each way, less than a page tall."""
    rects = [pymupdf.Rect(im["bbox"]) for im in page.get_image_info()]
    try:
        figures = [pymupdf.Rect(r) for r in page.cluster_drawings()]
    except Exception:
        figures = []
    if figures:
        try:
            tables = [pymupdf.Rect(t.bbox) for t in page.find_tables(clip=clip).tables]
        except Exception:
            tables = []
        for r in figures:
            if any((r & t).get_area() >= 0.5 * r.get_area() for t in tables):
                continue
            rects.append(r)
    return [r for r in rects
            if r.width >= 20 and r.height >= 20 and r.height < 0.85 * page.rect.height
            and r.y1 > clip.y0 + 0.5 and r.y0 < clip.y1 - 0.5
            and r.x1 > clip.x0 and r.x0 < clip.x1]


def keep_bands(page, clips):
    """The clips, each grown to whole words, overlaps merged, sorted down the page.

    Grown because apply_redactions deletes any glyph its rectangle TOUCHES, so a word
    lying across the edge of a clip would vanish from the visible crop too.

    Kept as separate bands rather than one bounding box because a lettered part is
    cropped together with the shared stem above it. What sits between those two is a
    different part's question, and inside a bounding box it would survive as invisible
    selectable text.
    """
    words = page.get_text("words")
    grown = []
    for c in clips:
        edge = [w for w in words if pymupdf.Rect(w[:4]).intersects(c)]
        grown.append(pymupdf.Rect(
            min([c.x0] + [w[0] for w in edge]), min([c.y0] + [w[1] for w in edge]),
            max([c.x1] + [w[2] for w in edge]), max([c.y1] + [w[3] for w in edge])))
    grown.sort(key=lambda r: r.y0)
    merged = []
    for b in grown:
        if merged and b.y0 <= merged[-1].y1 + 1:
            merged[-1] |= b
        else:
            merged.append(pymupdf.Rect(b))
    return merged


def dead_zones(page_rect, bands):
    """Everything outside `bands`: the gaps between them, the space above the first
    and below the last, and the margin either side of each."""
    out, top = [], page_rect.y0
    for b in bands:
        out.append(pymupdf.Rect(page_rect.x0, top, page_rect.x1, b.y0))
        out.append(pymupdf.Rect(page_rect.x0, b.y0, b.x0, b.y1))
        out.append(pymupdf.Rect(b.x1, b.y0, page_rect.x1, b.y1))
        top = b.y1
    out.append(pymupdf.Rect(page_rect.x0, top, page_rect.x1, page_rect.y1))
    return [r for r in out if r.height > 1 and r.width > 1]


def redacted_copy(doc, page_index, keep):
    """A one-page copy of `doc[page_index]` with all text outside `keep` deleted.

    show_pdf_page(clip=...) hides the rest of the source page but still copies its
    whole content stream, so anything outside the clip survives in the output file as
    invisible, selectable, searchable text. Redaction removes the glyphs for real.

    Called once per placed slice rather than once per question because a long question
    is placed in slices down successive output pages, and each of those slices would
    otherwise carry the whole question's text. On Business Paper 2, where the stimulus
    makes almost every question split, that was 41% of the words in the file.
    """
    out = pymupdf.open()
    out.insert_pdf(doc, from_page=page_index, to_page=page_index)
    page = out[0]
    for dead in dead_zones(page.rect, keep_bands(page, [keep])):
        page.add_redact_annot(dead)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    return out


class PageFlow:
    """Packs items (question crops, answer rows) one after another down the
    page and only turns to a fresh A4 sheet when the next one won't fit -
    one page per question left most of every sheet blank."""

    def __init__(self, out_doc):
        self.out_doc = out_doc
        self.page = None
        self.cursor = TOP_MARGIN

    def _new_page(self):
        self.page = self.out_doc.new_page(width=PAGE_W, height=PAGE_H)
        self.cursor = TOP_MARGIN

    def compact(self):
        """show_pdf_page copies each source page's full resources (fonts,
        images) into out_doc on every call, uncompressed and with no
        de-duplication - fine for a few dozen items, but a 200+ question
        chapter accumulates gigabytes in memory before the one save() at
        the very end ever gets a chance to garbage-collect it. Periodically
        write-then-reopen (the same garbage=4/deflate/clean cleanup used on
        final save) to keep memory bounded through a long build instead of
        only cleaning up once at the finish line."""
        if self.page is None:
            return
        page_num = self.page.number
        data = self.out_doc.write(garbage=4, deflate=True, clean=True)
        self.out_doc.close()
        self.out_doc = pymupdf.open(stream=data, filetype="pdf")
        self.page = self.out_doc[page_num]

    def place(self, src_doc, page_index, clips, label, qnum, header_fn=None,
              split_each_clip=False):
        """clips: one pymupdf.Rect, or a list of them in reading order that
        together make up ONE logical item - e.g. a shared question stem plus
        one lettered sub-part's own body, kept as separate rects because
        they aren't vertically contiguous in the source PDF. An entry may be
        a bare Rect (on `page_index`) or a (page_index, Rect) pair, so an
        item that runs across several source pages stays one item. The
        citation is drawn once at the very start of the item, and again only
        if the item has to spill onto a fresh output page - never just
        because it moved from one clip to the next."""
        if isinstance(clips, pymupdf.Rect):
            clips = [clips]
        clips = [c if isinstance(c, tuple) else (page_index, c) for c in clips]
        if self.page is None:
            self._new_page()
        header_h = CITE_H + CONTENT_PAD + (20 if header_fn else 0)
        min_useful = header_h + 30  # citation + header + a little content - below this, just start fresh
        # A mark-scheme row wider than the page was being placed at its source width,
        # so its right-hand side - often the Marks column itself - fell off the sheet
        # and was gone for good. Scale the item down to fit instead of clipping it.
        # ponytail: one scale for the whole item, not per slice, so an item that
        # splits across two output pages stays the same size on both.
        k = min(1.0, USABLE_W / max(c.width for _, c in clips))
        x0 = LEFT_MARGIN if k < 1 else None     # scaled items lose the source indent
        total_h = sum(c.height for _, c in clips) * k
        placed_any = False
        need_header = True
        for src_page, clip in clips:
            remaining_top, bottom = clip.y0, clip.y1
            cut_points = None  # computed lazily - most items never need to split at all
            obj_cuts = None
            clip_start = True
            while remaining_top < bottom - 0.5:
                available = PAGE_H - BOTTOM_MARGIN - self.cursor
                reserve = min_useful if need_header else 20
                if available < reserve:
                    self._new_page()
                    need_header = True
                    available = PAGE_H - BOTTOM_MARGIN - self.cursor
                # F-IT-ANSWERS-ROWNOTFOUND: never turn an empty page - an item taller
                # than three pages (a whole practical mark scheme) left a blank sheet.
                elif split_each_clip and placed_any and clip_start and self.cursor > TOP_MARGIN:
                    # The same "no lone leftover line" rule for each later clip of the
                    # item. A practical task's mark scheme is one clip per source page,
                    # and its next row used to start in the last sliver of the page with
                    # only its label line, the rest of the row overleaf.
                    fitting = available - (header_h if need_header else 0)
                    clip_h = (bottom - remaining_top) * k
                    if fitting < clip_h and fitting / clip_h < MIN_SPLIT_FRACTION:
                        self._new_page()
                        need_header = True
                        available = PAGE_H - BOTTOM_MARGIN - self.cursor
                elif not placed_any and self.cursor > TOP_MARGIN:
                    # Would this item have to split right here? Only worth it if
                    # a decent chunk of it stays on this page - otherwise a lone
                    # leftover line before the reader has to flip the page is
                    # more annoying than just starting the whole thing fresh.
                    fitting_content_h = available - header_h
                    if fitting_content_h < total_h and fitting_content_h / total_h < MIN_SPLIT_FRACTION:
                        self._new_page()
                        need_header = True
                        available = PAGE_H - BOTTOM_MARGIN - self.cursor
                # B3-crop-bounds (F-IT-PAGES-CLIP-OBJECT): a split must not run through a
                # picture or a figure. When the part that would fit on this sheet ends
                # nowhere clean, turn the page first and split on the fresh one instead
                # (where an object taller than a sheet is the only thing left to cut).
                y_body = self.cursor + (header_h if need_header else 0)
                fit_end = remaining_top + min((PAGE_H - BOTTOM_MARGIN - y_body) / k,
                                              bottom - remaining_top)
                if fit_end < bottom - 0.5:
                    if obj_cuts is None:
                        obj_cuts = safe_cut_points(src_doc, src_page, clip, objects=True)
                    if (self.cursor > TOP_MARGIN
                            and not any(remaining_top + MIN_SLICE <= c <= fit_end
                                        for c in obj_cuts)):
                        self._new_page()
                        need_header = True
                        continue
                y = self.cursor
                if need_header:
                    draw_item_citation(self.page, y, label, qnum, continued=placed_any)
                    y += CITE_H + CONTENT_PAD
                    if header_fn:
                        y = header_fn(self.page, clip, y)
                    need_header = False
                slice_h = min((PAGE_H - BOTTOM_MARGIN - y) / k, bottom - remaining_top)
                slice_end = remaining_top + slice_h
                if slice_end < bottom - 0.5:  # forced split - snap to a real gap between lines
                    if cut_points is None:
                        cut_points = safe_cut_points(src_doc, src_page, clip)
                    candidates = ([c for c in (obj_cuts or []) if remaining_top < c <= slice_end]
                                  or [c for c in cut_points if remaining_top < c <= slice_end])
                    if candidates:
                        slice_end = candidates[-1]
                    slice_h = slice_end - remaining_top
                src_slice = pymupdf.Rect(clip.x0, remaining_top, clip.x1, remaining_top + slice_h)
                left = clip.x0 if x0 is None else x0
                target = pymupdf.Rect(left, y, left + clip.width * k, y + slice_h * k)
                sub = redacted_copy(src_doc, src_page, src_slice)
                self.page.show_pdf_page(target, sub, 0, clip=src_slice)
                sub.close()
                remaining_top += slice_h
                self.cursor = y + slice_h * k + ITEM_GAP
                placed_any = True
                clip_start = False
                if remaining_top < bottom - 0.5:
                    self._new_page()
                    need_header = True


def build_questions_pdf(examples, out_path):
    out_doc = pymupdf.open()
    flow = PageFlow(out_doc)
    for qp_name, _ms_name, qnum, label in examples:
        src = pymupdf.open(PDF_DIR / qp_name)
        page_index, top, bottom = find_question_crop(src, qnum)
        clip = pymupdf.Rect(LEFT_MARGIN, top, RIGHT_MARGIN, bottom)
        flow.place(src, page_index, clip, label, qnum)
        src.close()
    out_doc.save(out_path, garbage=4, deflate=True, clean=True)
    out_doc.close()


def draw_ms_header(out_page, clip, y):
    # Reconstruct the "Question | Answer | Marks" header ourselves, matching
    # the mark scheme's own column x-positions, rather than cropping it from
    # the source (other questions' rows usually sit between the header and
    # the row we actually want in the original table).
    x0, x1 = clip.x0, clip.x1
    col_q, col_a, col_m = x0 + 5, x0 + 65, x1 - 45
    for x, t in ((col_q, "Question"), (col_a, "Answer"), (col_m, "Marks")):
        out_page.insert_text((x, y), t, fontname="hebo", fontsize=10, color=(0, 0, 0))
    out_page.draw_line((x0, y + 6), (x1, y + 6), color=(0, 0, 0), width=0.6)
    return y + 20


def build_answers_pdf(examples, out_path):
    out_doc = pymupdf.open()
    flow = PageFlow(out_doc)
    for _qp_name, ms_name, qnum, label in examples:
        src = pymupdf.open(PDF_DIR / ms_name)
        page_index, row_bbox = find_answer_row(src, qnum)
        clip = pymupdf.Rect(*row_bbox)
        flow.place(src, page_index, clip, label, qnum, header_fn=draw_ms_header)
        src.close()
    out_doc.save(out_path, garbage=4, deflate=True, clean=True)
    out_doc.close()


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    build_questions_pdf(EXAMPLES, OUT_DIR / "poc_chapter_questions.pdf")
    build_answers_pdf(EXAMPLES, OUT_DIR / "poc_chapter_answers.pdf")
    print("wrote Reports/poc_chapter_questions.pdf and Reports/poc_chapter_answers.pdf")

# NOT handled in this POC (deliberately, to keep it small enough to react to):
#   - questions split mid-way for topic tagging (e.g. "8(a)" vs "8(b)" from
#     one PDF question) - those need a sub-part y-boundary, not just a
#     whole-question one. Doable with the same SUBPART regex split_papers.py
#     already uses, just not wired up here.
#   - "page render, unverified placement" entries (vector-drawn diagrams) -
#     those already ARE a rasterised whole-page image in Text/images/, so
#     they'd crop the same way but need the placement flagged as unverified.
#   - duplicate P11/P13, P31/P33 zone-variant headers (pick either source).
