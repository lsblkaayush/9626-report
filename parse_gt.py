"""Grade threshold PDFs -> data/grade_thresholds.json.

Two tables per PDF: per-component raw marks, and per-option weighted totals.
Layout has been stable since 2017 apart from the header casing, so one regex each.

ponytail: regex over pdftotext -layout, no PDF table model. Fine while CAIE keeps
the one-subject-per-file format; revisit if they go back to bundling subjects.
"""
import json, re, subprocess
from pathlib import Path

GT = Path("PDFs/Grade Thresholds")
OUT = Path("data/grade_thresholds.json")
SESSION = {"m": "March", "s": "June", "w": "November"}

COMPONENT = re.compile(r"Component\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)")
OPTION = re.compile(
    r"^\s*([A-Z]{2}[JN]?)\s+(?:(\d{3})\s+)?((?:\d\d,\s*)+\d\d)\s+([\d–-]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$",
    re.M)


def parse(pdf):
    txt = subprocess.run(["pdftotext", "-layout", str(pdf), "-"],
                         capture_output=True, text=True, check=True).stdout
    code = pdf.stem.split("_")[1]                      # e.g. s25
    comps = {}
    for m in COMPONENT.finditer(txt):
        c, mx, a, b, cc, d, e = m.groups()
        comps[c.zfill(2)] = {"max": int(mx), "A": int(a), "B": int(b),
                             "C": int(cc), "D": int(d), "E": int(e)}
    opts = {}
    for m in OPTION.finditer(txt):
        name, mx, combo, astar, a, b, c, d, e = m.groups()
        opts[name] = {"components": re.sub(r"\s+", " ", combo),
                      "max": int(mx) if mx else None,
                      "A*": None if astar in "–-" else int(astar),
                      "A": int(a), "B": int(b), "C": int(c), "D": int(d), "E": int(e)}
    return code, {"session": SESSION[code[0]], "year": 2000 + int(code[1:]),
                  "components": comps, "options": opts}


if __name__ == "__main__":
    data = dict(sorted(parse(p) for p in GT.glob("9626_*_gt.pdf")))
    OUT.write_text(json.dumps(data, indent=1))
    bad = [k for k, v in data.items() if not v["components"] or not v["options"]]
    print(f"{len(data)} sessions -> {OUT}" + (f"  INCOMPLETE: {bad}" if bad else ""))
