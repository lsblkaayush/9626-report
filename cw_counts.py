"""data/cw_parts.json -> data/cw_counts.json: the one set of numbers the report uses.

Papers 1 and 3, 2022 onward. A part counts under the command word in its own text; a part
with none of its own (e.g. "(b) Trojan" under an Identify stem) counts as "no command word"
and is reported as such, not guessed. OVERRIDE fixes parts the automatic match got wrong,
each checked by hand against the question paper.
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OVERRIDE = {("9626_w24_qp_33", "3", "b"): "Describe"}  # 'contrast' is an image term there

def counts():
    rows = json.load(open(ROOT / "data" / "cw_parts.json"))
    rec = [r for r in rows if r["year"] >= 2022]
    parts, with_ms, marks = Counter(), Counter(), Counter()
    for r in rec:
        w = OVERRIDE.get((r["doc"], r["q"], r["part"]), r["cw"]) or "none"
        parts[w] += 1; marks[w] += r["marks"]
        if r["ms"]: with_ms[w] += 1
    total = sum(marks.values())
    return {"papers": len({r["doc"] for r in rec}), "parts_total": len(rec), "marks_total": total,
            "words": {w: {"parts": parts[w], "with_mark_scheme": with_ms[w], "marks": marks[w],
                          "share_pct": round(100 * marks[w] / total, 1)} for w, _ in marks.most_common()}}

if __name__ == "__main__":
    c = counts()
    (ROOT / "data" / "cw_counts.json").write_text(json.dumps(c, indent=1))
    for w, v in c["words"].items(): print(f"{w:22} parts {v['parts']:4}  with MS {v['with_mark_scheme']:4}  {v['share_pct']}%")
