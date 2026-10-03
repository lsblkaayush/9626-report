"""
9626 Paper 3 -> per-paper Markdown, with questions + mark scheme answers
merged, diagrams pulled out as images, marks shown per part.

NOT included on purpose: topic tagging. You said your local agent will do
that pass against the syllabus PDF, so this only does the mechanical work -
extraction, pairing, formatting - and leaves classification to it.

USAGE:
    pip install pymupdf --break-system-packages
    Put BOTH the question paper and mark scheme PDFs in a folder "PDFs/"
    next to this script, using Cambridge's original filenames (the qp/ms
    pairing below depends on them, e.g. 9626_s24_qp_31.pdf + 9626_s24_ms_31.pdf).
    python split_papers.py

OUTPUT ("Text/"):
    <original qp filename>.md   - one per paper, questions + matched answers
    images/<papercode>/*.png    - every diagram found, referenced from the .md

HONESTY NOTES (read before trusting this blind):
  - Question-number detection uses PDF font metadata, not text pattern
    matching: Cambridge renders a real question number as BOLD text sitting
    at the page's left margin (x0 ~ 50pt), consistently from 2017 through
    2025 papers checked. Sub-part labels like "(a)" are also bold but
    indented further right (x0 ~ 72pt), and embedded code listings (e.g. a
    JavaScript snippet shown IN a question, numbered 1-19) use a non-bold
    monospace font - so neither is mistaken for a new question anymore.
    An earlier regex-on-text version of this script got both of those
    wrong and silently corrupted papers; this was caught by manually
    reading two generated files against their source PDFs. Spans are the
    reliable signal here, not the text shape.
  - Embedded raster images (photos, screenshots) extract cleanly with real
    page-position matching to a question.
  - VECTOR-DRAWN diagrams (network diagrams, flowcharts made of lines/boxes,
    which p3 questions on networks/system design use a lot) are NOT
    embedded images - PDFs draw them as line/shape instructions, so there's
    nothing to "extract" the normal way. Where a page has enough drawing
    commands to look like it holds one, this renders THE WHOLE PAGE as a
    fallback image and labels it "page render, unverified placement" rather
    than pretending a clean per-question crop. Trust that label.
  - Mark scheme matching tries a table extraction first (Cambridge tabulates
    Question | Answer | Marks in every MS checked), falls back to the same
    left-margin-bold-number split used for the QP if no clean table is
    found on a page.
"""

import re
from pathlib import Path
import pymupdf

SRC = Path("PDFs")
OUT = Path("Text")
IMG_DIR = OUT / "images"

SUBPART = re.compile(r"^\s{0,4}\(([a-h]|[ivx]{1,4})\)\s+")
MARKS = re.compile(r"\[(\d{1,2})\]\s*$")
LEADING_QNUM = re.compile(r"^(\d{1,2})(?=\s|$)")
# Papers 2 and 4 (practical) label work "Task 1", "Task 2" ... instead of a bare
# number, at the same left margin. Same role, different label.
LEADING_TASK = re.compile(r"^Task\s+(\d{1,2}[a-z]?)(?=\s|$)", re.I)
DRAWING_THRESHOLD = 12  # get_drawings() items above this -> "probably a diagram"
QNUM_LEFT_MARGIN_MAX_X = 56  # real question numbers sit at x0 ~50; spreadsheet row headers shown inside a question sit at ~60-64


# ── low-level extraction ─────────────────────────────────────────────────
def doc_has_named_bold_font(doc) -> bool:
    """True if this PDF's fonts still carry real names (older papers: e.g.
    "Arial-BoldMT" vs "ArialMT" - lets us require bold for a question
    number). 2024+ papers ship a subsetted, security-obfuscated font
    ("AllAndNone"/"AllAndNone2") where every span looks identical - for
    those, bold can't be checked at all, and margin position has to carry
    the whole rule on its own."""
    for page in doc:
        for f in page.get_fonts():
            basefont = f[3]
            if "allandnone" in basefont.lower():
                return False
    return True


def is_question_start_line(line_text: str, first_span, require_bold: bool) -> str | None:
    """A genuine question number: the line's text opens with "N " or is just
    "N", AND the line sits at the page's left margin. Checking the whole
    line's text (not just the first span) matters because some papers merge
    the number and the question text into one PDF text run - "10 JavaScript
    code can be..." as a single span - so a first-span-must-be-pure-digit
    check would miss it. Sub-part labels like "(a)" sit further right
    (~72pt) and code-listing line numbers shown IN a question sit either
    further right too, or (on older papers, where fonts still carry real
    names) in a non-bold span - so bold is required wherever the document's
    fonts make that distinction available."""
    m = LEADING_QNUM.match(line_text) or LEADING_TASK.match(line_text)
    if not m:
        return None
    if first_span["bbox"][0] >= QNUM_LEFT_MARGIN_MAX_X:
        return None
    if require_bold and "bold" not in first_span["font"].lower():
        return None
    return m.group(1)


def page_lines(page, require_bold: bool):
    """[(text, top_y, qnum_or_None), ...] for one page, reading order, via
    the text dict so every line carries its vertical position (needed to
    place images) and, if it opens a new question, that question's number."""
    lines = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = line["spans"]
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            qnum = is_question_start_line(text, spans[0], require_bold) if spans else None
            lines.append((text, line["bbox"][1], qnum))
    return lines


def extract_raster_images(doc, page, papercode, page_num, img_dir):
    """Embedded (non-vector) images on this page -> saved files, with the y
    position they sit at so they can be matched to a question block."""
    out = []
    for idx, img in enumerate(page.get_images(full=True)):
        xref = img[0]
        try:
            rects = page.get_image_rects(xref)
            top = rects[0].y0 if rects else 0
            base = doc.extract_image(xref)
            fname = f"{papercode}_p{page_num}_img{idx}.{base['ext']}"
            (img_dir / fname).write_bytes(base["image"])
            out.append((fname, top))
        except Exception:
            continue  # a broken image xref shouldn't kill the whole page
    return out


def maybe_render_page_for_diagram(page, papercode, page_num, img_dir):
    """Vector-drawing fallback: if this page looks diagram-heavy, render the
    whole page and flag it as unverified placement. Returns (fname, top_y)
    using the REAL top of the drawing-heavy region (not a fixed page-top
    guess) - a diagram-bearing question that starts fresh at the top of a
    page is the common case, and pinning this to a fake position would have
    attached it to the previous question instead, every time."""
    drawings = [d for d in page.get_drawings() if d.get("items")]
    item_count = sum(len(d["items"]) for d in drawings)
    if item_count < DRAWING_THRESHOLD:
        return None
    top = min(d["rect"].y0 for d in drawings if d.get("rect") is not None)
    pix = page.get_pixmap(dpi=150)
    fname = f"{papercode}_p{page_num}_pagerender.png"
    pix.save(img_dir / fname)
    return fname, top


# ── question / answer splitting ──────────────────────────────────────────
def continues_sequence(qnum: str, previous: str | None) -> bool:
    """Real question numbers run 1, 2, 3... (with the practicals occasionally
    splitting one into "1a"/"1b"). Bold digits at the left margin that DON'T
    continue the sequence are figure labels bleeding through - a timeline axis
    starting at "0", a table's row header - not a new question. Checking the
    running sequence kills those without needing per-paper special cases."""
    n = int(re.match(r"\d+", qnum).group(0))
    if previous is None:
        return n == 1
    prev_n = int(re.match(r"\d+", previous).group(0))
    return n == prev_n + 1 or (n == prev_n and qnum != previous)


def split_into_questions(lines):
    """[(qnum, [line_texts...]), ...]. Lines before Q1 (instructions) are
    dropped since a line only ever joins a block once a question-start line
    has been seen at least once."""
    blocks, current, qnum = [], [], None
    for text, _top, line_qnum in lines:
        if line_qnum is not None and continues_sequence(line_qnum, qnum):
            if qnum is not None:
                blocks.append((qnum, current))
            qnum, current = line_qnum, [text]
        elif qnum is not None:
            current.append(text)
    if qnum is not None:
        blocks.append((qnum, current))
    return blocks


def marks_in(lines_text: list[str]) -> int:
    total = 0
    for t in lines_text:
        m = MARKS.search(t)
        if m:
            total += int(m.group(1))
    return total


def format_question_body(lines_text: list[str]) -> str:
    """Question text -> markdown, bolding sub-part marks and indenting
    (a)/(i) style sub-parts so the structure is visually obvious."""
    out = []
    for t in lines_text:
        m = MARKS.search(t)
        body, mk = (t[:m.start()].rstrip(), m.group(1)) if m else (t, None)
        prefix = "  - " if SUBPART.match(t) else ""
        line = f"{prefix}{body}"
        if mk:
            line += f"  **[{mk}]**"
        out.append(line)
    return "\n".join(out)


# ── mark scheme ───────────────────────────────────────────────────────────
def clean_ms_text(s: str) -> str:
    """Cambridge MS PDFs use Symbol-font private-use characters for bullets
    (U+F0B7, sometimes immediately followed by a U+F020 "space" glyph from
    the same font) and multiplication signs (U+F0B4) - map them to real
    markdown/unicode so the output isn't full of missing-glyph boxes."""
    s = s.replace("", "×").replace("", " ")
    out = []
    for ln in s.split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith(""):
            out.append("- " + ln[1:].strip())
        else:
            out.append(ln)
    return "\n".join(out)


def format_ms_row(cells: list[str]) -> str:
    if not cells:
        return ""
    marks = cells[-1].strip() if cells[-1].strip().isdigit() else None
    body_cells = cells[:-1] if marks else cells
    body = clean_ms_text("\n\n".join(body_cells))
    return f"{body}\n\n**Marks: {marks}**" if marks else body


def extract_ms_answers(ms_path: Path) -> dict[str, str]:
    """Best-effort qnum -> answer markdown. Table pass first, line-split
    fallback second. Returns {} (not an exception) if the MS can't be read,
    so a missing/odd mark scheme never takes the QP output down with it."""
    answers: dict[str, list[str]] = {}
    try:
        doc = pymupdf.open(ms_path)
    except Exception:
        return {}

    used_table = False
    for page in doc:
        try:
            tables = page.find_tables()
        except Exception:
            tables = []
        for t in tables:
            rows = t.extract()
            if not rows:
                continue
            for row in rows:
                if not row or not row[0]:
                    continue
                qtext = str(row[0]).strip()
                # Mark schemes label sub-part rows "1(a)", "1(b)" instead of
                # repeating a plain "1" - and some go a level deeper still,
                # "10(i)" or "6(a)(i)" for a lettered part with roman-numeral
                # sub-parts. Match any of these, keyed to the base question
                # number so every sub-part answer lands together under it.
                m = re.match(r"^([1-9]|1[0-9]|20)(?:\s*\([a-h]\))?(?:\s*\([ivx]+\))?$", qtext)
                if not m:
                    continue
                used_table = True
                qnum = m.group(1)
                cells = [str(c).strip() for c in row[1:] if c]
                answers.setdefault(qnum, []).append(format_ms_row(cells))

    if not used_table:
        # Fallback: same left-margin-number split used for the QP.
        require_bold = doc_has_named_bold_font(doc)
        all_lines = []
        for page in doc:
            all_lines.extend(page_lines(page, require_bold))
        for qnum, body in split_into_questions(all_lines):
            answers.setdefault(qnum, []).append(clean_ms_text("\n".join(body)))

    doc.close()
    return {q: "\n\n".join(v) for q, v in answers.items()}


# ── per-paper driver ──────────────────────────────────────────────────────
def find_ms_for(qp_path: Path) -> Path | None:
    if "qp" not in qp_path.name.lower():
        return None
    candidate_name = re.sub(r"qp", "ms", qp_path.name, flags=re.IGNORECASE, count=1)
    candidate = qp_path.with_name(candidate_name)
    return candidate if candidate.exists() else None


def process_paper(qp_path: Path):
    """Single linear pass over the whole document in reading order (page,
    then vertical position), text and images interleaved as one event
    stream. An image is attached to whichever question is textually
    "current" at that point - i.e. the same question a human reading top to
    bottom would associate it with - rather than to every question that
    happens to share its page (that was the v1 bug: two questions on one
    page both claimed the same diagram)."""
    papercode = qp_path.stem
    doc = pymupdf.open(qp_path)
    img_dir = IMG_DIR / papercode
    img_dir.mkdir(parents=True, exist_ok=True)

    require_bold = doc_has_named_bold_font(doc)
    events = []  # (page_num, top_y, kind, payload)
    for pnum, page in enumerate(doc, start=1):
        for text, top, qnum in page_lines(page, require_bold):
            events.append((pnum, top, "text", (text, qnum)))
        if pnum == 1:
            continue  # cover page: instructions + logo, never a real question
        for fname, top in extract_raster_images(doc, page, papercode, pnum, img_dir):
            events.append((pnum, top, "image", fname))
        rendered = maybe_render_page_for_diagram(page, papercode, pnum, img_dir)
        if rendered:
            fname, top = rendered
            events.append((pnum, top, "pagerender", fname))
    doc.close()
    events.sort(key=lambda e: (e[0], e[1]))

    blocks: list[list] = []  # [qnum, [(kind, payload), ...]]
    current = None
    for _pnum, _top, kind, payload in events:
        if kind == "text" and payload[1] is not None and continues_sequence(
            payload[1], blocks[-1][0] if blocks else None
        ):
            current = [payload[1], []]
            blocks.append(current)
        if current is None:
            continue  # instructions before Question 1
        entry = ("text", payload[0]) if kind == "text" else (kind, payload)
        current[1].append(entry)

    ms_path = find_ms_for(qp_path)
    ms_answers = extract_ms_answers(ms_path) if ms_path else {}

    md = [f"# {papercode}\n"]
    if ms_path is None:
        md.append("> _No matching mark scheme file found next to this question paper._\n")

    for qnum, entries in blocks:
        body_lines = [p for k, p in entries if k == "text"]
        total = marks_in(body_lines)
        md.append(f"## Question {qnum}" + (f" — {total} marks" if total else ""))
        md.append(format_question_body(body_lines))

        for kind, payload in entries:
            if kind == "image":
                md.append(f"\n![Q{qnum} diagram](images/{papercode}/{payload})")
            elif kind == "pagerender":
                md.append(f"\n![Q{qnum} — page render, unverified placement, "
                           f"check against source PDF](images/{papercode}/{payload})")

        md.append("\n### Mark scheme")
        if qnum in ms_answers:
            md.append(ms_answers[qnum])
        elif ms_path is not None:
            md.append(f"_No answer auto-matched for Q{qnum} — check `{ms_path.name}` manually._")
        else:
            md.append("_No mark scheme file available._")
        md.append("\n---\n")

    # Practical mark schemes (Papers 2 and 4) are rubric lists grouped by task, with
    # no per-question column to key off - so per-question matching often misses. Rather
    # than silently drop the marking detail, dump the whole scheme verbatim at the end
    # whenever anything went unmatched. Unsorted, but nothing is lost.
    if ms_path is not None and any(q not in ms_answers for q, _ in blocks):
        raw = "\n".join(clean_ms_text(pg.get_text()) for pg in pymupdf.open(ms_path))
        md.append(f"## Full mark scheme (verbatim, unsorted)\n")
        md.append(f"_Source: `{ms_path.name}`. Included because per-question matching "
                  f"did not cover every question in this paper._\n")
        md.append(raw)

    (OUT / f"{papercode}.md").write_text("\n".join(md), encoding="utf-8")
    return len(blocks)


def main():
    if not SRC.exists():
        print(f"Put QP + MS PDFs in a folder called '{SRC}/' next to this script, then re-run.")
        return
    OUT.mkdir(exist_ok=True)
    IMG_DIR.mkdir(exist_ok=True)

    qp_files = sorted(p for p in SRC.glob("*.pdf") if "qp" in p.name.lower())
    if not qp_files:
        print("No question-paper PDFs found (looking for 'qp' in the filename).")
        return

    for qp in qp_files:
        n = process_paper(qp)
        ms = find_ms_for(qp)
        print(f"{qp.name}: {n} questions written -> {qp.stem}.md"
              f"  [mark scheme: {'found' if ms else 'MISSING'}]")


if __name__ == "__main__":
    main()
