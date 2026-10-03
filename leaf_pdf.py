"""Cover pages and page banners so a QP.pdf and its MS.pdf can be read side by side
without the reader ever having to work out what they are looking at.

Two problems this fixes:
  - the cropped PDFs carried a per-question citation but no statement of WHICH chapter,
    session or paper the file as a whole is
  - the mark schemes that couldn't be cropped were raw CAIE pages with no marker at all,
    so a reader landing on page 3 had no idea which task it answered

Every page of every output now says what it is, and both files share the same
"Task N" vocabulary so they line up.
"""
import pymupdf

INK = (0.10, 0.12, 0.16)
MUTED = (0.42, 0.45, 0.52)
RULE = (0.78, 0.80, 0.85)
ACCENT = (0.05, 0.35, 0.62)
WARN = (0.70, 0.33, 0.05)
BANNER_H = 26


def _wrap(text, width, size, font="helv"):
    out, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if pymupdf.get_text_length(trial, fontname=font, fontsize=size) > width:
            out.append(line)
            line = word
        else:
            line = trial
    if line:
        out.append(line)
    return out


def cover(doc, *, kind, chapter, level, paper_code, session, qnums, marks,
          files, ms_mode, also=(), at_start=True):
    """Prepend a cover page. `kind` is "QUESTIONS" or "MARK SCHEME"."""
    page = doc.new_page(0 if at_start else -1, width=595, height=842)
    x0, x1, y = 56, 539, 92

    page.insert_text((x0, y), kind, fontname="hebo", fontsize=9, color=ACCENT)
    y += 30
    for ln in _wrap(chapter, x1 - x0, 23, "hebo"):
        page.insert_text((x0, y), ln, fontname="hebo", fontsize=23, color=INK)
        y += 28
    y += 4
    page.insert_text((x0, y), f"{level}   ·   Paper {paper_code}   ·   {session}",
                     fontname="helv", fontsize=12, color=MUTED)
    y += 26
    page.draw_line((x0, y), (x1, y), color=RULE, width=0.8)
    y += 30

    total = sum(marks.get(q, 0) for q in qnums)
    rows = [("Tasks in this file", ", ".join(qnums)),
            ("Marks", f"{total}" if total else "see mark scheme")]
    # files=None means the concept doesn't apply here (theory); [] means it applies
    # and there genuinely are none.
    if kind == "QUESTIONS" and files is not None:
        rows.append(("Source files", ", ".join(files) if files else
                     "none — these tasks are built from scratch"))
    # One integrated task can examine two chapters; naming them here stops a reader
    # deciding the file has been misfiled when it opens on the other chapter's work.
    if also:
        rows.append(("Also covers", "; ".join(also)))
    for lbl, val in rows:
        page.insert_text((x0, y), lbl, fontname="hebo", fontsize=9.5, color=MUTED)
        yy = y
        for ln in _wrap(val, x1 - (x0 + 130), 11):
            page.insert_text((x0 + 130, yy), ln, fontname="helv", fontsize=11, color=INK)
            yy += 15
        y = yy + 11

    y += 12
    page.draw_line((x0, y), (x1, y), color=RULE, width=0.8)
    y += 26

    if kind == "MARK SCHEME" and ms_mode == "whole":
        page.draw_rect(pymupdf.Rect(x0, y - 14, x1, y + 46), color=None,
                       fill=(0.99, 0.955, 0.90))
        page.insert_text((x0 + 12, y + 3), "This is the complete mark scheme for the paper.",
                         fontname="hebo", fontsize=10, color=WARN)
        note = ("Cambridge laid this session out as screenshots under loose headings, with no "
                f"per-task rows to cut to. Look for {', '.join('Task ' + q for q in qnums)}. "
                "Keeping it whole is deliberate — it beats pairing a task with the wrong answer.")
        yy = y + 19
        for ln in _wrap(note, x1 - x0 - 24, 9):
            page.insert_text((x0 + 12, yy), ln, fontname="helv", fontsize=9, color=INK)
            yy += 11
        y = yy + 20
    elif kind == "MARK SCHEME" and ms_mode == "split":
        note = ("Full mark scheme pages covering this chapter's tasks. This session has no "
                "per-part rows to cut to, so whole pages are included; other tasks may appear "
                "alongside.")
        for ln in _wrap(note, x1 - x0, 9.5):
            page.insert_text((x0, y), ln, fontname="helv", fontsize=9.5, color=MUTED)
            y += 12
        y += 14

    foot = ("Every page is banner-labelled with the paper and session, so this file and its "
            "counterpart can be read side by side.")
    yy = 792
    for ln in _wrap(foot, x1 - x0, 8.5):
        page.insert_text((x0, yy), ln, fontname="helv", fontsize=8.5, color=MUTED)
        yy += 10
    return page


def banner(page, *, left, right):
    """Stamp a labelled strip across the top of a raw CAIE page.

    Drawn inside the top margin, above where Cambridge starts its own header text, and
    on an opaque band so the decoy page number underneath doesn't show through and
    confuse the reader about which page they are on.
    """
    # Some CAIE mark scheme pages are landscape via /Rotate. Drawing commands take
    # unrotated coordinates, so map through the derotation matrix - otherwise the strip
    # lands sideways down the edge of the page instead of across its top.
    w = page.rect.width
    m, rot = page.derotation_matrix, page.rotation
    tw = pymupdf.get_text_length(right, fontname="helv", fontsize=8.5)
    page.draw_rect(pymupdf.Rect(0, 0, w, BANNER_H) * m, color=None, fill=(1, 1, 1))
    page.draw_rect(pymupdf.Rect(0, 0, 4.5, BANNER_H) * m, color=None, fill=ACCENT)
    page.insert_text(pymupdf.Point(14, 16) * m, left, fontname="hebo", fontsize=8.5,
                     color=ACCENT, rotate=rot)
    page.insert_text(pymupdf.Point(w - 14 - tw, 16) * m, right, fontname="helv", fontsize=8.5,
                     color=MUTED, rotate=rot)
    page.draw_line(pymupdf.Point(0, BANNER_H) * m, pymupdf.Point(w, BANNER_H) * m,
                   color=RULE, width=0.7)


def demo():
    """One runnable check: a cover renders, a banner lands in the top margin, and the
    whole-mode warning actually reaches the page text."""
    doc = pymupdf.open()
    doc.new_page(width=595, height=842)
    cover(doc, kind="MARK SCHEME", chapter="10 Database and file concepts",
          level="AS Level", paper_code="02", session="May/June 2024",
          qnums=["1", "2"], marks={"1": 16, "2": 12}, files=["a.csv"], ms_mode="whole")
    t = doc[0].get_text()
    assert "MARK SCHEME" in t and "Database" in t, t[:200]
    assert "28" in t, "marks should total 16+12"
    assert "Task 1, Task 2" in t, "whole-mode note must name the tasks"
    doc2 = pymupdf.open()
    doc2.new_page(width=595, height=842)
    cover(doc2, kind="QUESTIONS", chapter="10 Database and file concepts",
          level="A Level", paper_code="04", session="October/November 2023",
          qnums=["2"], marks={"2": 30}, files=["F2uF.ods"], ms_mode="cropped",
          also=["18 Mail merge"])
    assert "Also covers" in doc2[0].get_text(), "shared-chapter row must reach the cover"
    assert "18 Mail merge" in doc2[0].get_text()

    banner(doc[1], left="MARK SCHEME · 9626/02 · May/June 2024", right="page 1 of 1")
    b = doc[1].get_text()
    assert "9626/02" in b, b[:120]
    for blk in doc[1].get_text("blocks"):
        if "9626/02" in blk[4]:
            assert blk[1] < BANNER_H, f"banner must sit in the top margin, got y={blk[1]}"
    print("ok  cover renders, marks total, whole-mode note names tasks, shared row, banner in margin")
    print("demo passed")


if __name__ == "__main__":
    demo()
