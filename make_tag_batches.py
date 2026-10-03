"""
question bank -> tagging batch files for the subagents.

Each batch is a self-contained Markdown file: one '### UNIT <id>' section per
taggable unit with its stem, question and a mark scheme excerpt. Duplicate
reprints are skipped (they inherit their keeper's tags).

    python3 scripts/make_tag_batches.py [outdir] [--size N] [--only-untagged]

--only-untagged reads data/untagged_units.txt and batches just those, so a run
that died partway can be resumed without re-paying for work already done.
Bigger --size means fewer agents and so fewer re-reads of the syllabus
reference, which is the main fixed cost per agent.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

args = [a for a in sys.argv[1:] if not a.startswith("--")]
flags = {a for a in sys.argv[1:] if a.startswith("--")}
OUTDIR = Path(args[0]) if args else ROOT / "tag_batches"
SIZE = 80
for f in flags:
    if f.startswith("--size="):
        SIZE = int(f.split("=", 1)[1])
if "--size" in sys.argv:
    SIZE = int(sys.argv[sys.argv.index("--size") + 1])


def paper_no(pc):
    v = pc.split("_")[-1]
    return v[1] if v[0] == "0" else v[0]


def order(r):
    m = re.match(r"9626_([msw])(\d{2})_qp_(\d{2})", r["paper"])
    se, yy, var = m.groups()
    qn = re.match(r"\d+", r["q"])
    return (paper_no(r["paper"]), int(yy), {"m": 0, "s": 1, "w": 2}[se], var,
            int(qn.group()) if qn else 0, r["part"] or "")


def trunc(t, n):
    t = (t or "").strip()
    return t if len(t) <= n else t[:n].rsplit("\n", 1)[0] + "\n[...truncated...]"


def main():
    bank = json.loads((DATA / "question_bank.json").read_text())
    units = [r for r in bank if "dupe_of" not in r]

    if "--only-untagged" in flags:
        wanted = set((DATA / "untagged_units.txt").read_text().split())
        units = [r for r in units
                 if f"{r['paper']}:{r['q']}{r['part'] or ''}" in wanted]

    units.sort(key=order)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    for f in OUTDIR.glob("batch_*.md"):
        f.unlink()

    batches = [units[i:i + SIZE] for i in range(0, len(units), SIZE)]
    index = {}
    for bi, batch in enumerate(batches, 1):
        papers = sorted({paper_no(r["paper"]) for r in batch})
        out = [f"# Tagging batch {bi:02d} of {len(batches)} - Paper(s) {', '.join(papers)}",
               f"{len(batch)} units. Tag EVERY unit. Output one JSONL line per unit id.\n"]
        ids = []
        for r in batch:
            uid = f"{r['paper']}:{r['q']}{r['part'] or ''}"
            ids.append(uid)
            out.append("\n---\n### UNIT " + uid)
            out.append(f"paper: {r['paper']} | question: {r['q']}{r['part'] or ''} "
                       f"| marks: {r['marks']}")
            if r.get("stem"):
                out.append("\n**Question stem (shared):**\n" + trunc(r["stem"], 700))
            if r.get("part_stem"):
                out.append("\n**Part stem:**\n" + trunc(r["part_stem"], 400))
            out.append("\n**Question:**\n" + trunc(r["text"], 1200))
            if r["ms"].strip():
                out.append("\n**Mark scheme (excerpt):**\n" + trunc(r["ms"], 900))
        (OUTDIR / f"batch_{bi:02d}.md").write_text("\n".join(out), encoding="utf-8")
        index[f"batch_{bi:02d}"] = ids

    (OUTDIR / "batch_ids.json").write_text(json.dumps(index, indent=1))
    print(f"{len(units)} units -> {len(batches)} batches of up to {SIZE} in {OUTDIR}")
    for name, ids in index.items():
        print(f"  {name}: {len(ids)} units")


if __name__ == "__main__":
    main()
