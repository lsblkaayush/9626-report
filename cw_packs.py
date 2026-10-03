"""data/cw_parts.json + data/cw_pages.jsonl -> data/cw_packs/<Word>.md

One evidence file per command word (or group of words that are taught together). Each file
holds every 2022-onward question part that uses the word, with its mark scheme and the
examiner report comment, and every examiner-report sentence from any year that names the
word. Drafting works only from these files, so every claim has something to cite.

ponytail: big words (Describe, Explain) are capped at the parts whose ER comment is about
that part specifically, then the rest by marks; the cap is printed so nobody mistakes the
pack for the whole population. Counts in the report come from cw_parts.json, not the pack.
"""
import json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GROUPS = {
    "Describe": ["Describe"], "Explain": ["Explain"], "Discuss": ["Discuss"],
    "Evaluate_Assess": ["Evaluate", "Assess"], "Analyse": ["Analyse"], "Justify": ["Justify"],
    "Compare_Contrast": ["Compare", "Contrast", "Compare and contrast"],
    "Short_answer": ["Identify", "State", "Give", "Define", "Name", "List", "Suggest"],
    "Algorithm_tasks": ["Complete", "Draw", "Write"],
}
CAP = 70

def sentences_naming(words):
    rx = re.compile(r"[^.]*\b(" + "|".join(w.lower() for w in words) + r"|"
                    + "|".join(w.lower()[:-1] + "(?:ing|ion|ions|ed|es)" for w in words) + r")\b[^.]*\.", re.I)
    out = []
    for l in open(ROOT / "data" / "cw_pages.jsonl"):
        p = json.loads(l)
        if p["kind"] != "er": continue
        for m in rx.finditer(p["text"]):
            s = m.group(0).strip()
            if 30 < len(s) < 700: out.append(f"- [{p['doc']} p{p['page']}] {s}")
    return out

def main():
    rows = json.load(open(ROOT / "data" / "cw_parts.json"))
    # a part with no command word of its own ("(b) Trojan") inherits the previous part's
    last = {}
    for r in rows:
        key = (r["doc"], r["q"])
        if not r["cw"] and key in last: r["cw"] = last[key]
        if r["cw"]: last[key] = r["cw"]
    outdir = ROOT / "data" / "cw_packs"; outdir.mkdir(exist_ok=True)
    for name, words in GROUPS.items():
        parts = [r for r in rows if r["cw"] in words and r["year"] >= 2022]
        allp = len(parts)
        parts.sort(key=lambda r: (r["er"] is None, (r["er"] or {}).get("scope") != "part", -r["marks"]))
        parts = parts[:CAP]
        lines = [f"# Evidence pack: {', '.join(words)}",
                 f"{allp} question parts from 2022 onward use this; {len(parts)} shown.", ""]
        for r in parts:
            ref = f"{r['doc']} Q{r['q']}{r['part'] or ''}"
            lines += [f"## {ref} [{r['marks']} marks] command word: {r['cw']}",
                      f"QUESTION: {r['question']}",
                      "MARK SCHEME (" + r['ms_doc'] + "): " + re.sub(r"\s+", " ", r['ms'] or 'not matched')[:1500]]
            if r["er"]:
                lines.append(f"EXAMINER REPORT ({r['er_doc']} p{r['er']['page']}, comment on the {r['er']['scope']}): {r['er']['text'][:1500]}")
            lines.append("")
        lines += ["# Examiner-report sentences naming the word (all years)", ""] + sentences_naming(words)
        (outdir / f"{name}.md").write_text("\n".join(lines))
        print(f"{name:18} {allp:4} parts, pack {len(parts)}")

if __name__ == "__main__":
    main()
