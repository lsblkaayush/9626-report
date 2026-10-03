"""Recount the three Discuss figures the teacher queried, and list every mark scheme behind each,
so each number can be checked by opening the PDFs. Writes Reports/discuss_count_check.md.

Rules (Papers 1 and 3, 2022 onward, Discuss parts with a matched mark scheme):
  per-side MAX   a MAX printed against one side (Benefits/Advantages/Drawbacks/...);
                 a cap on a definition ("Max one for: Definition") or on bullets does not count
  both sides     "at least two/one of each" (or two benefits and two drawbacks) for full marks
  one-side cap   "Max N if all benefits or all drawbacks" style
  opening mark   a separately labelled mark for defining or describing the thing in the question;
                 listed by hand below because the wording varies too much for a pattern
"""
import json, re
from pathlib import Path
from cw_counts import OVERRIDE

ROOT = Path(__file__).resolve().parent
SIDE = r"(benefits?|advantages?|drawbacks?|disadvantages?|positives?|negatives?)"
OPENING = ["9626_s24_ms_12 Q7", "9626_s25_ms_12 Q13", "9626_w23_ms_12 Q11", "9626_w25_ms_11 Q13",
           "9626_w25_ms_13 Q13", "9626_m24_ms_32 Q8", "9626_m24_ms_32 Q11", "9626_m25_ms_32 Q10",
           "9626_s22_ms_31 Q4", "9626_s22_ms_32 Q6", "9626_s22_ms_33 Q4", "9626_s24_ms_31 Q4",
           "9626_s24_ms_33 Q4", "9626_s25_ms_31 Q7", "9626_w23_ms_32 Q10", "9626_w24_ms_32 Q5",
           "9626_w25_ms_32 Q7", "9626_w25_ms_33 Q11"]

def main():
    rows = json.load(open(ROOT / "data" / "cw_parts.json"))
    D = [r for r in rows if r["year"] >= 2022 and r["ms"]
         and OVERRIDE.get((r["doc"], r["q"], r["part"]), r["cw"]) == "Discuss"]
    lists = {"per-side MAX": [], "at least two on each side": [], "at least one on each side": [],
             "limit if all on one side": []}
    for r in D:
        ms = re.sub(r"\s+", " ", r["ms"]); ref = f'{r["ms_doc"]} Q{r["q"]}{r["part"] or ""}'
        hits = [m.group(0) for m in re.finditer(r".{0,35}\bmax\b.{0,35}", ms, re.I)]
        if any(re.search(SIDE, h, re.I) and not re.search(r"bullets|list of points|if all|expansion", h, re.I) for h in hits):
            lists["per-side MAX"].append(ref)
        if re.search(r"at least (two|2) (of each|from each|benefits|positive|advantages)", ms, re.I):
            lists["at least two on each side"].append(ref)
        if re.search(r"at least (one|1) of each", ms, re.I):
            lists["at least one on each side"].append(ref)
        if re.search(r"if all (benefits|advantages|for)", ms, re.I):
            lists["limit if all on one side"].append(ref)
    lists["opening definition or description mark"] = OPENING
    out = [f"# Discuss counts: {len(D)} mark schemes (Papers 1 and 3, 2022 onward)", ""]
    for k, v in lists.items():
        out += [f"## {k}: {len(v)}", ""] + [f"- {x}" for x in v] + [""]
    (ROOT / "Reports" / "discuss_count_check.md").write_text("\n".join(out))
    for k, v in lists.items(): print(f"{k}: {len(v)}")

if __name__ == "__main__":
    main()
