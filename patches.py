"""
Known one-off content fixes for specific papers, applied AFTER split_papers.py.
These are real defects found by manually reading generated output against the
source PDF - not things worth generalizing the extraction script for, since
each affects exactly one question out of 602. Re-run this after any re-run of
split_papers.py (a fresh `rm -rf Text/*` wipes these).

USAGE: python patches.py
"""

from pathlib import Path

TEXT = Path(__file__).parent / "Text"


def fix_w18_qp_33_q3_stem():
    """A flowchart-heavy page (lots of vector-drawing content) disrupted
    text reading order, so Q3's stem - "Evaluate the use of Bluetooth(R)
    wireless technology..." - got swept into Q2's block instead of Q3's,
    leaving Q3 looking empty (just the answer-space dots). Confirmed via
    the mark scheme, which is about Bluetooth and correctly attached to Q3.
    Moves the one stem line to where it belongs."""
    path = TEXT / "9626_w18_qp_33.md"
    text = path.read_text(encoding="utf-8")
    stem = "Evaluate the use of Bluetooth® wireless technology for communication between devices."

    misplaced = f"{stem}\n\n![Q2 — page render, unverified placement, check against source PDF](images/9626_w18_qp_33/9626_w18_qp_33_p4_pagerender.png)"
    fixed_q2_tail = "![Q2 — page render, unverified placement, check against source PDF](images/9626_w18_qp_33/9626_w18_qp_33_p4_pagerender.png)"
    if misplaced in text:
        text = text.replace(misplaced, fixed_q2_tail)

    empty_q3 = "## Question 3 — 8 marks\n3\n.........."
    fixed_q3 = f"## Question 3 — 8 marks\n3\n{stem}\n.........."
    if empty_q3 in text and stem not in text.split("## Question 3", 1)[1][:200]:
        text = text.replace(empty_q3, fixed_q3)

    path.write_text(text, encoding="utf-8")


def fix_s18_qp_32_checkbox_glyph():
    """A single checkbox icon in a form screenshot (Fig. 1, Q1) comes
    through as U+F0FC (a Wingdings-derived private-use codepoint with no
    real glyph) - the only such stray codepoint across all 55 question
    papers. Maps it to a real checkbox character."""
    path = TEXT / "9626_s18_qp_32.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("", "☐")
    path.write_text(text, encoding="utf-8")


def main():
    fix_w18_qp_33_q3_stem()
    fix_s18_qp_32_checkbox_glyph()
    print("Patches applied.")


if __name__ == "__main__":
    main()
