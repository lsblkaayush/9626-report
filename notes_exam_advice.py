"""Move exam advice in Notes/AS Theory (Short)/*.md to the end of each chapter.

Students may meet a chapter for the first time in these notes, so a chapter opens with the content. The
"Most marks come from" block and any answer rules that sat above the first section, and the per-section
priority lines, become one closing section: "## Exam advice for this chapter". Priority comes from recent
(2022-2025) Paper 1 marks in the tagging data. Idempotent: a chapter that already has the section is rebuilt.
"""
import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes" / "AS Theory (Short)"
HEAD = "## Exam advice for this chapter"


def marks_per_paper():
    bank = {u["paper"] + ":" + u["q"] + (u["part"] or ""): u for u in json.load(open(ROOT / "data" / "question_bank.json"))}
    rec, papers = collections.Counter(), set()
    for line in open(ROOT / "data" / "tagging_manifest_p1.jsonl"):
        e = json.loads(line)
        t = e.get("topics")
        p = e["id"].split(":")[0]
        if not t or not 22 <= int(p.split("_")[1][1:3]) <= 25:
            continue
        papers.add(p)
        m = (bank.get(e["id"]) or {}).get("marks") or 0
        for s in t:
            rec[s] += m / len(t)
    return {s: v / len(papers) for s, v in rec.items()}


def label(v):
    n = round(v)
    tier = "HIGH" if n >= 3 else "MEDIUM" if n == 2 else "LOW"
    if v < 0.25:
        return f"{tier}, rarely asked since 2022 but still examinable"
    n = max(1, n)
    return f"{tier}, about {n} mark{'s' if n != 1 else ''} in a typical Paper 1"


def rebuild(path, per):
    text = path.read_text().rstrip("\n")
    if HEAD in text:  # rebuild from an earlier run: take the old advice back out first
        text, old = text.split("\n" + HEAD, 1)
        top_old = re.split(r"\n### Where the marks are\n", old)[0]
        rest = re.split(r"\n### Where the marks are\n.*?(?=\n### |\Z)", old, flags=re.S)
        top = "".join(rest).strip().replace("### Most marks come from\n", "### Most marks come from (2017 to 2025 papers)\n")
        lines = text.split("\n")
        title, body = lines[0], "\n".join(lines[1:])
    else:
        lines = text.split("\n")
        title = lines[0]
        first = next(i for i, l in enumerate(lines) if l.startswith("## "))
        top = "\n".join(lines[1:first]).strip()
        top = re.sub(r"\n-{3,}\s*$", "", top).strip()
        body = "\n".join(lines[first:])
        top = re.sub(r"^\*\*Most marks come from:?\*\*:?", "### Most marks come from (2017 to 2025 papers)", top, flags=re.M)
    # priority lines out of the body
    body = re.sub(r"\n\*Priority:[^\n]*\*\n(\s*\n)?", "\n", body)
    subs = []
    for m in re.finditer(r"^##\s+((\d+\.\d+)\b.*)$", body, flags=re.M):
        if m.group(2) not in [s for s, _ in subs]:
            subs.append((m.group(2), m.group(1).strip()))
    where = "\n".join(f"- **{name}**: {label(per.get(s, 0))}" for s, name in subs)
    advice = (f"{HEAD}\n\n### Where the marks are\n\nFrom the 2022 to 2025 Paper 1 papers. Every part can still be asked.\n\n"
              f"{where}\n\n{top}\n")
    path.write_text(f"{title}\n\n{body.strip()}\n\n{advice}")
    return len(subs)


def main():
    per = marks_per_paper()
    files = [NOTES / a for a in sys.argv[1:]] or sorted(NOTES.glob("[0-9]*.md"))
    for f in files:
        print(f.name, rebuild(f, per), "subtopics")


if __name__ == "__main__":
    main()
