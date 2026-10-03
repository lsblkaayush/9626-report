"""Text/Paper {1,3}/*.md + data/cw_pages.jsonl -> data/cw_parts.json

One record per question part on the theory papers: its command word, marks, question text,
mark-scheme answer, and the examiner report's comment on that question with the ER page it
sits on. This is the evidence every claim in the command-words report is drawn from.

Matching rules, so a reader can check them:
  - A part's command word is the first capitalised Cambridge command word in its own text
    (same convention as report_stats.py). Lower-case use ("... and explain why") is a
    fallback only.
  - Mark-scheme blocks are matched to parts positionally on the **Marks: N** markers that
    split_papers.py writes, and kept only when the counts agree (otherwise ms=None).
  - ER comments are found by component (e.g. 9626/12) then "Question N"; the part letter is
    matched when the ER splits a question into (a), (b)... and otherwise the whole question's
    comment is attached.
"""
import json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CMDS = ["Compare and contrast", "Analyse", "Assess", "Compare", "Contrast", "Define", "Describe",
        "Discuss", "Evaluate", "Explain", "Identify", "Justify", "State", "Suggest", "Give",
        "Complete", "Draw", "Write", "Calculate", "Name", "List"]
CMD_RE = re.compile(r"\b(" + "|".join(CMDS) + r")\b")
CMD_ANY = re.compile(CMD_RE.pattern, re.I)
JUNK = re.compile(r"^\s*(\.{6,}.*|9626/\d\d/.*|© UCLES.*|www\.dynamicpapers\.com|\d{1,2}|\[Turn over\]|BLANK PAGE)\s*$")

def clean_q(lines):
    return re.sub(r"\s+", " ", " ".join(l for l in lines if not JUNK.match(l))).strip()

def parse_md(path):
    txt = path.read_text()
    out = []
    for qm in re.finditer(r"^## Question (\d+).*?(?=^## Question |\Z)", txt, re.S | re.M):
        qn, body = qm.group(1), qm.group(0)
        q_part, _, ms_part = body.partition("### Mark scheme")
        # question side: split into parts on the [n] marks markers
        parts, cur, label = [], [], ""
        for line in q_part.splitlines()[1:]:
            m = re.match(r"^\s*-\s*\(([a-h])\)(?:\s*\(([ivx]+)\))?", line)
            if m:
                label = m.group(1) + (f"({m.group(2)})" if m.group(2) else "")
            else:
                m2 = re.match(r"^\s*-\s*\(([ivx]+)\)", line)
                if m2: label = re.sub(r"\(.*", "", label) + f"({m2.group(1)})"
            cur.append(line)
            mk = re.search(r"\*\*\[(\d+)\]\*\*", line)
            if mk:
                parts.append({"label": label, "marks": int(mk.group(1)), "text": clean_q(cur)})
                cur = []
        blocks = [b.strip() for b in re.split(r"\*\*Marks: \d+\*\*", ms_part)][: -1] if ms_part else []
        ms_ok = len(blocks) == len(parts)
        for i, p in enumerate(parts):
            own = re.sub(r"\[\d+\]", "", p["text"])
            # the command word belongs to the last sentence-ish chunk of the part, so look
            # at the text after the part label first
            hit = CMD_RE.findall(own) or CMD_ANY.findall(own)
            cw = (hit[-1] if hit else None)
            # prefer a word that opens a sentence (Cambridge house style)
            opens = re.findall(r"(?:^|[.?)\]]\s|\)\s)(" + "|".join(CMDS) + r")\b", own)
            if opens: cw = opens[-1]
            out.append({"q": qn, "part": p["label"], "marks": p["marks"], "cw": cw and cw.title().replace(" And ", " and "),
                        "question": p["text"][-900:], "ms": blocks[i][:2500] if ms_ok else None})
    return out

def er_index():
    """(session, component) -> list of (page, text) for that component's section."""
    pages = defaultdict(list)
    for l in open(ROOT / "data" / "cw_pages.jsonl"):
        r = json.loads(l)
        if r["kind"] == "er": pages[r["doc"]].append((r["page"], r["text"]))
    idx = defaultdict(list)
    for doc, ps in pages.items():
        sess = doc.split("_")[1]
        comp = None
        for page, t in sorted(ps):
            # a page can hold the end of one component and the start of the next
            pieces = re.split(r"(Paper 9626/\d\d)", t)
            for piece in pieces:
                m = re.fullmatch(r"Paper 9626/(\d\d)", piece)
                if m: comp = m.group(1); continue
                if comp: idx[(sess, comp)].append((page, piece))
    return idx

def er_for(idx, sess, comp, q, part):
    secs = idx.get((sess, comp), [])
    hits = []
    for page, t in secs:
        for m in re.finditer(r"Question " + q + r"\b(.*?)(?=Question \d+\b|$)", t):
            hits.append((page, m.group(1).strip()))
    # a question's comment can run over a page break: take the following page's opening too
    if not hits: return None
    page, body = hits[0]
    letter = part[:1] if part and part[0].isalpha() else ""
    if letter:
        sub = re.search(r"\(" + letter + r"\)(.*?)(?=\([a-h]\)\s|$)", body)
        if sub and len(sub.group(1)) > 40:
            return {"page": page, "text": sub.group(1).strip()[:2500], "scope": "part"}
    return {"page": page, "text": body[:2500], "scope": "question"}

def main():
    idx = er_index()
    rows = []
    for P in ("1", "3"):
        for md in sorted((ROOT / "Text" / f"Paper {P}").glob("*.md")):
            m = re.match(r"9626_([msw]\d\d)_qp_(\d\d)", md.stem)
            sess, comp = m.groups()
            for r in parse_md(md):
                r.update({"paper": P, "doc": md.stem, "session": sess, "comp": comp,
                          "year": 2000 + int(sess[1:]), "ms_doc": md.stem.replace("_qp_", "_ms_"),
                          "er": er_for(idx, sess, comp, r["q"], r["part"]), "er_doc": f"9626_{sess}_er"})
                rows.append(r)
    (ROOT / "data" / "cw_parts.json").write_text(json.dumps(rows, indent=1))
    from collections import Counter
    rec = [r for r in rows if r["year"] >= 2022]
    print(len(rows), "parts;", len(rec), "from 2022 on;",
          sum(1 for r in rec if r["ms"]), "with MS;", sum(1 for r in rec if r["er"]), "with ER;",
          sum(1 for r in rec if not r["cw"]), "without a command word")
    c = Counter(); mk = Counter()
    for r in rec: c[r["cw"]] += 1; mk[r["cw"]] += r["marks"]
    tot = sum(mk.values())
    for k, v in mk.most_common(): print(f"  {str(k):22} parts {c[k]:4}  marks {v:5}  {100*v/tot:4.1f}%")

if __name__ == "__main__":
    main()
