"""What the practical papers ask you to *do*, counted over every sitting.

Papers 2 and 4 are graded on operations, not on recall, so a topic share does not
tell a candidate what to practise. This walks the question papers and the published
mark schemes for components 02 and 04 and counts, for each skill, how many of the
sittings need it.

Two passes, kept apart on purpose:

  skills    - matched on task wording. A question paper says "trim the clip", so the
              wording is reliable evidence that the sitting wanted that operation.
  functions - matched on a spreadsheet function written as a formula, VLOOKUP( and
              not the word lookup. Question papers almost never name a function; the
              mark scheme does, and only when it chooses to print the formula rather
              than describe the result. So these counts are a floor, not a census.

Output: data/practical_skills.json. Re-run it when a new practical mark scheme lands.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COMPONENT = {"2": "02", "4": "04"}

# Page furniture that sits in every paper and every mark scheme. Left in, "Principal
# Examiner Report for Teachers" alone puts a database "report" in all 27 sittings.
BOILER = re.compile(r"Principal Examiner Report[^.]*|www\.dynamicpapers\.com"
                    r"|Cambridge International[^\n]*|UCLES[^\n]*", re.I)

SKILLS = {
    "2": [
        ("Exporting to the named file", r"\bexport\b|\.mp4|\.mp3|\.wav|\.avi"),
        ("Trimming and cropping video", r"\btrim(med|ming)?\b|\bcrop\b|still (image|frame)|\bsplit\b"),
        ("Transitions, titles and captions", r"transition|title (clip|frame|sequence|screen)|as a[^.]{0,12} title|caption|subtitle|credits"),
        ("Keys, relationships and 3NF", r"primary key|foreign key|relationship|one.to.many|normalis"),
        ("Validation and test data", r"validation|test (plan|data)|abnormal|extreme data"),
        ("Audio editing", r"fade (in|out)|soundtrack|amplif|\bmono\b|\bstereo\b|sample rate|bit ?rate"),
        ("Absolute and relative references", r"absolute (cell )?ref|relative (cell )?ref|replicat|\$[A-Z]{1,2}\$"),
        ("Database reports and forms", r"create (a|an appropriate)? ?report|database report|report (layout|structure|title)|data entry form"),
        ("Charts and graphs", r"\bchart\b|\bgraph\b|pivot table"),
        ("Conditional formatting", r"conditional format"),
        ("Queries", r"\bquer(y|ies)\b"),
    ],
    "4": [
        ("Animation", r"\btween|keyframe|onion skin|frame rate|\banimat"),
        ("HTML and CSS", r"\bhtml\b|\bcss\b|stylesheet|<[a-z]+>"),
        ("Vector graphics", r"vector|b(e|.)zier|convert to curves|gradient|\bnode\b"),
        ("JavaScript", r"javascript|\.js\b|onclick|\bscript\b"),
        ("Image editing", r"\bclone\b|\bheal\b|\bmask\b|opacity|transparen"),
        ("Mail merge", r"mail ?merge|MERGEFIELD|SKIPIF|merge field"),
        ("Charts and graphs", r"\bchart\b|\bgraph\b"),
        ("SQL", r"\bSQL\b|SELECT .*FROM|INNER JOIN"),
        ("Pivot tables", r"pivot"),
        ("What-if modelling", r"what.if|goal seek|scenario|solver"),
    ],
}

# Grouped the way a candidate would revise them, not the way a spreadsheet manual
# lists them. Longest name first inside each family so COUNTIFS wins over COUNTIF.
FAMILIES = [
    ("Lookups", ["VLOOKUP", "HLOOKUP", "XLOOKUP", "LOOKUP", "INDEX", "MATCH"]),
    ("IF and nested IF", ["IFERROR", "ISERROR", "ISNUMBER", "ISNONTEXT", "ISTEXT", "IFS", "IF"]),
    ("Conditional counts and totals", ["COUNTIFS", "COUNTIF", "SUMIFS", "SUMIF",
                                       "AVERAGEIFS", "AVERAGEIF"]),
    ("Text handling", ["CONCATENATE", "TEXTJOIN", "SUBSTITUTE", "SEARCH", "UPPER",
                       "LOWER", "TRIM", "LEFT", "RIGHT", "FIND", "MID", "LEN"]),
    ("Rounding and whole numbers", ["ROUNDDOWN", "ROUNDUP", "ROUND", "INT", "MOD"]),
    ("Totals and averages", ["SUBTOTAL", "AVERAGE", "COUNTA", "COUNT", "SUM", "MAX",
                             "MIN", "RANK"]),
    ("Dates", ["WEEKDAY", "TODAY", "MONTH", "YEAR", "DAY"]),
    ("Merge fields", ["MERGEFIELD", "SKIPIF"]),
]


def clean(text):
    return BOILER.sub(" ", text)


def sittings(paper):
    """{'9626_m17': text of the question papers and the mark scheme for that sitting}."""
    comp = COMPONENT[paper]
    out = defaultdict(str)
    for f in sorted((ROOT / "Text" / f"Paper {paper}").glob(f"*_qp_{comp}.md")):
        out[f.stem[:8]] += " " + clean(f.read_text())
    for f in sorted((ROOT / "PDFs" / f"Paper {paper}").glob(f"*_ms_{comp}.pdf")):
        with pymupdf.open(f) as d:
            text = "\n".join(p.get_text() for p in d)
        # Everything above the first "Task" is the generic marking principles, which
        # are identical in all 27 mark schemes.
        cut = text.find("Task")
        out[f.stem[:8]] += " " + clean(text[cut:] if cut > 0 else text)
    return dict(out)


def build(paper):
    text = sittings(paper)
    n = len(text)
    skills = [{"name": name, "papers": sum(bool(re.search(pat, t, re.I))
                                           for t in text.values())}
              for name, pat in SKILLS[paper]]
    skills.sort(key=lambda s: -s["papers"])

    named = {}
    for _, members in FAMILIES:
        for fn in members:
            hits = sum(bool(re.search(r"\b" + fn + r" *\(", t)) for t in text.values())
            if hits:
                named[fn] = hits
    families = []
    for title, members in FAMILIES:
        seen = [m for m in members if m in named]
        if not seen:
            continue
        # A sitting counts once for the family however many of its functions it uses.
        papers = sum(any(re.search(r"\b" + m + r" *\(", t) for m in members)
                     for t in text.values())
        families.append({"name": title, "papers": papers,
                         "members": sorted(seen, key=lambda m: -named[m])})
    families.sort(key=lambda f: -f["papers"])
    return {"sittings": n, "skills": skills, "functions": named, "families": families}


if __name__ == "__main__":
    out = {p: build(p) for p in COMPONENT}
    (DATA / "practical_skills.json").write_text(json.dumps(out, indent=1))
    for p, d in out.items():
        print(f"=== Paper {p}: {d['sittings']} sittings")
        for s in d["skills"]:
            print(f"   {s['papers']:3d}  {s['name']}")
        for f in d["families"]:
            print(f"   {f['papers']:3d}  {f['name']}: {', '.join(f['members'])}")
