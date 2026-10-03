"""Can a student actually sit each leaf? Cross-reference the filenames the questions
NAME against the files actually shipped in source/.

A "gap" is a file the question tells you to open that isn't there. Output files the
candidate is told to CREATE are not gaps - those are the answer, not the input.

USAGE: python3 scripts/audit_practical.py
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "Chapterwise Practical"
# No spaces: allowing them made the regex swallow the words before the name
# ("Use the Digits.png"). The handful of real names with a space are listed below.
FILE_RE = re.compile(
    r"(?<![\w.-])([A-Za-z0-9][A-Za-z0-9_.\-]{0,40}?\.(?:csv|rtf|html?|ods|xlsx?|xls|png|jpe?g|mp3|mp4|svg|js|txt|gif|mov|wmv|wav|docx?))(?![\w-])",
    re.I)
# The Text/ extractor injects figure placeholders; they are not source files.
ARTEFACT = re.compile(r"^9626_[msw]\d\d_qp_\d+_p\d+_(img|pagerender)", re.I)
MEDIA = {".mp3", ".mp4", ".mov", ".wmv", ".wav", ".gif"}
IMAGE = {".png", ".jpg", ".jpeg", ".svg"}
# The candidate is told to SAVE these; they are deliverables, not inputs. A later task
# then reopens them ("Open the files: n22student.csv, n22timetable.csv"), so the only
# reliable signal is an explicit "save ... as <name>" anywhere in the paper.
SAVED_AS = re.compile(
    r"(?:save|saved|saving|store)\b[^.]{0,80}?\bas\s+(?:a\s+\w+\s+)?([A-Za-z0-9][\w.\-]{0,40}?"
    r"\.(?:csv|rtf|html?|ods|xlsx?|xls|png|jpe?g|mp3|mp4|svg|js|txt|gif|mov|wmv|wav|docx?))", re.I)


def bank_text():
    idx, parent = {}, defaultdict(list)
    for x in json.load(open(ROOT / "data/question_bank.json")):
        q, p = x["q"], x["part"]
        body = " ".join(filter(None, [x.get("stem", ""), x.get("part_stem", ""), x.get("text", "")]))
        idx[(x["paper"], q if p in (None, "None", "") else f"{q}({p})")] = body
        parent[(x["paper"], q)].append(body)
    return idx, parent


def inputs_named(text, whole_paper):
    """Filenames the question tells you to OPEN. Anything the paper elsewhere tells the
    candidate to SAVE under that name is their own output, even where a later task
    reopens it, so it is never a missing source file."""
    outputs = {m.group(1).lower() for m in SAVED_AS.finditer(whole_paper)}
    names = set()
    for m in FILE_RE.finditer(text):
        name = m.group(1).strip()
        if re.match(r"^\d+\.\d+$", name) or ARTEFACT.match(name):
            continue
        if name.lower() in outputs or "zz999" in name.lower():
            continue
        names.add(name)
    return names


def main():
    idx, parent = bank_text()
    plan = json.load(open(ROOT / "data/practical_plan.json"))
    by_leaf = {}
    for g in plan:
        year = 2000 + int(g["session"][1:])
        if not 2020 <= year <= 2025:
            continue
        mon = {"m": "Mar", "s": "Jun", "w": "Nov"}[g["session"][0]]
        by_leaf[OUT / f"{g['level']}_{g['slug']}" / str(year) / f"{mon}_{year}"] = g

    rows = []
    for leaf, g in sorted(by_leaf.items()):
        have = {p.name for p in (leaf / "source").iterdir()} if (leaf / "source").is_dir() else set()
        have_l = {h.lower() for h in have}
        text = " ".join(idx.get((g["paper"], q)) or " ".join(parent.get((g["paper"], re.match(r"\d+", q).group()), []))
                        for q in g["qnums"])
        whole = " ".join(v for (pp, _), v in idx.items() if pp == g["paper"])
        want = inputs_named(text, whole)
        # a real name may contain a space the regex can't span ("JS Task.html")
        missing = sorted(n for n in want
                         if n.lower() not in have_l
                         and not any(h.endswith(n.lower()) for h in have_l))
        if missing:
            kinds = {Path(m).suffix.lower() for m in missing}
            kind = ("media" if kinds & MEDIA else "image" if kinds & IMAGE else "data")
            rows.append((leaf, g, missing, kind, sorted(have)))
    print(f"{len(by_leaf)} leaves audited, {len(rows)} with a named input file that isn't shipped\n")
    for leaf, g, missing, kind, have in rows:
        rel = leaf.relative_to(OUT)
        print(f"[{kind:5}] {str(rel):42} {g['paper']}")
        print(f"          missing: {', '.join(missing)}")
        print(f"          have:    {', '.join(have) or '(nothing)'}")
    json.dump([{"leaf": str(l.relative_to(OUT)), "paper": g["paper"], "slug": g["slug"],
                "level": g["level"], "missing": m, "kind": k, "have": h,
                "reconstructed": g["reconstructed"]}
               for l, g, m, k, h in rows],
              open(ROOT / "data/practical_audit.json", "w"), indent=1)
    print(f"\n-> data/practical_audit.json")


if __name__ == "__main__":
    main()
