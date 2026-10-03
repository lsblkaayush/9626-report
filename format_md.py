"""
Shared formatting helpers: turn extracted exam text into the Obsidian table
format used by the By Topic files.

The PDF extractor emits hard-wrapped lines. A wrapped continuation almost always
starts with a lowercase word, so that is what we join on. Every remaining logical
line is a point, and points are separated by a blank line (a '<br><br>' pair
inside a table cell).
"""
import re

CONT = re.compile(r"^\s*(?:\.{3}|…)")            # '...' sub-point marker
NUMWORD = re.compile(
    r"^((?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)) (from|marks?)\b",
    re.I)
BULLET = re.compile(r"^\s*[•–—\-\*·]\s+")


def reflow(text: str) -> list[str]:
    """Hard-wrapped text -> list of logical lines.

    Sub-point lines opening with '...' stay separate (they are continuations of
    the point above, but the mark scheme means them to read as their own line).
    """
    out = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            out.append("")
            continue
        stripped = line.strip()
        first = stripped[0]
        is_new = (
            not out or out[-1] == ""
            or CONT.match(stripped)
            or BULLET.match(stripped)
            or not (first.islower() or first in "/)")
        )
        if is_new:
            out.append(stripped if not CONT.match(stripped) else "    " + stripped)
        else:
            out[-1] = out[-1] + " " + stripped
    return [l for l in out if l != "" or True]


def to_cell(text: str, *, lead_in: bool = True) -> str:
    """Logical lines -> one Markdown table cell.

    Points are separated by a blank line ('<br><br>'). Two things hug the line
    above with a single '<br>' instead: a '...' sub-point, and the point that
    follows a short heading ending in ':' ('Benefits:').
    """
    text = re.sub(r"\*\*\[\d+\]\*\*", "", text)          # marks live in their own column
    lines = [l for l in reflow(text) if l.strip()]
    parts, hug_next = [], False
    for i, line in enumerate(lines):
        is_sub = bool(CONT.match(line.strip()))
        if i == 0 and lead_in and NUMWORD.match(line):
            line = NUMWORD.sub(lambda m: f"**{m.group(1)}** {m.group(2)}", line, count=1)
        if parts:
            parts.append(("<br>" if (hug_next or is_sub) else "<br><br>") + line)
        else:
            parts.append(line)
        # a short heading pulls the next point up against it: 'Benefits:', or a
        # bare 'Benefits' sitting directly above its bullet list
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        short = len(line.strip()) < 45
        hug_next = not is_sub and short and (
            line.rstrip().endswith(":")
            or (bool(BULLET.match(nxt)) and not line.rstrip()[-1:] in ".;")
        )
    return "".join(parts).replace("|", "\\|").strip()
