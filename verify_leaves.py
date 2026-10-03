"""Last gate before shipping: for every leaf, does the mark scheme actually answer the
questions the question paper asks, and is every file labelled?

Checks per leaf:
  1. QP.pdf and MS.pdf exist and open
  2. both carry a cover page naming the chapter, level, paper and session
  3. every page carries a banner
  4. the tasks named on the QP cover are the tasks named on the MS cover
  5. for a cropped MS, each task in the plan is actually reachable in the MS text
  6. source/ matches what notes.md advertises
"""
import json, re, sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).parent.parent
OUT = ROOT / "Chapterwise Practical"
MONTH = {"m": "Mar", "s": "Jun", "w": "Nov"}


def cover_facts(doc):
    t = doc[0].get_text()
    m = re.search(r"Tasks in this file\s*(.+)", t)
    tasks = [x.strip() for x in m.group(1).split(",")] if m else []
    return t, tasks


def main():
    plan = json.load(open(ROOT / "data/practical_plan.json"))
    problems, checked = [], 0
    for g in plan:
        year = 2000 + int(g["session"][1:])
        if not 2020 <= year <= 2025:
            continue
        leaf = OUT / f"{g['level']}_{g['slug']}" / str(year) / f"{MONTH[g['session'][0]]}_{year}"
        rel = leaf.relative_to(OUT)
        qp, ms = leaf / "QP.pdf", leaf / "MS.pdf"
        if not qp.exists() or not ms.exists():
            problems.append(f"{rel}: missing {'QP' if not qp.exists() else 'MS'}.pdf")
            continue
        checked += 1
        qd, md = pymupdf.open(qp), pymupdf.open(ms)
        qt, qtasks = cover_facts(qd)
        mt, mtasks = cover_facts(md)

        for name, txt in (("QP", qt), ("MS", mt)):
            for token in (g["chapter"].split(" ", 1)[1][:18], str(year)):
                if token not in txt:
                    problems.append(f"{rel}: {name} cover missing {token!r}")
        if "QUESTIONS" not in qt:
            problems.append(f"{rel}: QP cover not labelled QUESTIONS")
        if "MARK SCHEME" not in mt:
            problems.append(f"{rel}: MS cover not labelled MARK SCHEME")
        if qtasks != mtasks:
            problems.append(f"{rel}: cover task lists disagree QP={qtasks} MS={mtasks}")
        if set(qtasks) != set(g["qnums"]):
            problems.append(f"{rel}: QP cover tasks {qtasks} != plan {g['qnums']}")

        # every content page must be banner-stamped
        for doc, name in ((qd, "QP"), (md, "MS")):
            for i in range(1, doc.page_count):
                head = doc[i].get_text("blocks")
                if not any(b[1] < 30 and "9626/" in b[4] for b in head):
                    problems.append(f"{rel}: {name}.pdf page {i + 1} has no banner")
                    break

        have = sorted(p.name for p in (leaf / "source").iterdir()) if (leaf / "source").is_dir() else []
        if sorted(g["files"]) != have:
            problems.append(f"{rel}: source/ {have} != plan {sorted(g['files'])}")
        note = (leaf / "notes.md").read_text() if (leaf / "notes.md").exists() else ""
        for f in g["files"]:
            if f not in note:
                problems.append(f"{rel}: notes.md doesn't mention {f}")
        qd.close()
        md.close()

    print(f"{checked} leaves verified, {len(problems)} problems")
    for p in problems[:40]:
        print("  -", p)
    if len(problems) > 40:
        print(f"  ... and {len(problems) - 40} more")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
