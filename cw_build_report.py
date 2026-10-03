"""data/cw_sections/*.json -> Reports/Command words - what the examiners want.pdf

Run cw_verify.py first: this refuses to build if any cite lacks the page the verifier
fills in, so an unverified quote can never reach print. Shares of marks come from
data/cw_parts.json (Papers 1 and 3, 2022 onward). The PDF is printed from HTML by
cw_pdf.js (Playwright's Chromium).
"""
import html, json, re, subprocess, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEC = ROOT / "data" / "cw_sections"
OUT = ROOT / "Reports"
SESS = {"m": "March", "s": "June", "w": "November"}
ORDER = ["Describe", "Explain", "Discuss", "Evaluate_Assess", "Analyse", "Justify",
         "Compare_Contrast", "Short_answer", "Algorithm_tasks"]
TITLES = {"Evaluate_Assess": "Evaluate (and Assess)", "Compare_Contrast": "Compare and Contrast",
          "Short_answer": "Identify, State, Give, Define, Name, Suggest",
          "Algorithm_tasks": "Complete, Draw, Write (algorithms and flowcharts)"}
KIND = [("marks", "How the marks are given"), ("format", "How to write it"),
        ("mistake", "What goes wrong"), ("tip", "Tips")]
def e(t):
    return html.escape(t)

ABBR = [(r"\bERs\b", "examiner reports"), (r"\bER\b", "examiner report"), (r"\bMSs\b", "mark schemes"),
        (r"\bMS\b", "mark scheme"), (r"\bQPs?\b", "question paper")]

MON = {"m": "March", "s": "June", "w": "November"}

def readable_id(m):
    s, yy, kind, comp = m.group(1), m.group(2), m.group(3), m.group(4)
    name = {"er": "examiner report", "ms": "mark scheme", "qp": "question paper"}[kind]
    return f"{MON[s]} 20{yy} {name}" + (f" (Paper {comp})" if comp else "")

def prose(t):
    # document ids and session codes in drafted prose -> words a student can read
    t = re.sub(r"\b9626_([msw])(\d\d)_(er|ms|qp)(?:_(\d\d))?\b", readable_id, t)
    t = re.sub(r"\b([msw])(\d\d)_(er|ms|qp)(?:_(\d\d))?\b", readable_id, t)
    t = re.sub(r"\b([msw])(2[0-6]|1[7-9])\b", lambda m: f"{MON[m.group(1)]} 20{m.group(2)}", t)
    t = re.sub(r"\bP(\d\d)\b", r"Paper \1", t)
    for a, b in ABBR: t = re.sub(a, b, t)
    return html.escape(t)

def er_components():
    """doc -> {page: (component in force at the top of the page, [(offset, component), ...])}
    from the 'Paper 9626/NN' headings, so a quote is pinned to the heading above it."""
    from cw_verify import norm
    comp, cur = {}, {}
    for l in open(ROOT / "data" / "cw_pages.jsonl"):
        r = json.loads(l)
        if r["kind"] != "er": continue
        t = norm(r["text"])
        heads = [(m.start(), m.group(1)) for m in re.finditer(r"paper 9626/(\d\d)", t)]
        comp.setdefault(r["doc"], {})[r["page"]] = (cur.get(r["doc"]), heads, t)
        if heads: cur[r["doc"]] = heads[-1][1]
    return comp

def er_component(doc, page, quote):
    from cw_verify import norm
    top, heads, t = COMP[doc][page]
    at = t.find(norm(quote).strip(" ."))
    before = [c for off, c in heads if at >= 0 and off <= at]
    return before[-1] if before else top

COMP = None

def source(c):
    doc, page = c["doc"], c.get("page")
    if page is None:
        sys.exit(f"unverified cite {doc}: {c['quote'][:60]!r} - run cw_verify.py")
    if doc == "9626_syllabus_2025-2027": return f"Syllabus 2025 to 2027, p. {page}"
    if doc == "9626_learner_guide": return f"Cambridge Learner Guide for 9626, p. {page}"
    m = re.match(r"9626_([msw])(\d\d)_(er|ms|qp)(?:_(\d\d))?", doc)
    s, yy, kind, comp = m.groups()
    when = f"{SESS[s]} 20{yy}"
    if kind == "er":
        c_ = er_component(doc, page, c["quote"])
        return f"Examiner report, {when}" + (f", Paper 9626/{c_}" if c_ else "") + f", p. {page}"
    name = {"ms": "Mark scheme", "qp": "Question paper"}[kind]
    # only verified facts in a citation: the drafter's question label is not checked, the page is
    return f"{name} 9626/{comp}, {when}, p. {page}"

def cites_html(cites):
    out = []
    for c in cites:
        out.append(f'<div class="cite">“{e(c["quote"].strip())}”<span class="src"> {e(source(c))}</span></div>')
    return "".join(out)

def stats():
    rows = json.load(open(ROOT / "data" / "cw_parts.json"))
    last = {}
    for r in rows:
        k = (r["doc"], r["q"])
        if not r["cw"] and k in last: r["cw"] = last[k]
        if r["cw"]: last[k] = r["cw"]
    rec = [r for r in rows if r["year"] >= 2022]
    mk, n = Counter(), Counter()
    for r in rec:
        mk[r["cw"] or "none"] += r["marks"]; n[r["cw"] or "none"] += 1
    papers = len({r["doc"] for r in rec})
    return mk, n, sum(mk.values()), papers, len(rec)

def section_html(s, title):
    h = [f'<section class="word{" page" if title.startswith("Describe") else ""}"><h2>{e(title)}</h2>']
    for w in s.get("words", []):
        if not w.get("syllabus"):
            h.append(f'<div class="def"><b>{e(w["word"])}</b>: not in the syllabus list of command words. {e(w.get("note", ""))}</div>')
            continue
        q = SYLLABUS.get(w["word"])
        if q:
            h.append(f'<div class="def"><b>{e(w["word"])}</b>. Cambridge’s definition: “{e(q)}”'
                     f'<span class="src"> Syllabus 2025 to 2027, p. 66</span></div>')
        else:
            h.append(f'<div class="def"><b>{e(w["word"])}</b>: not in the syllabus table of command words. '
                     f'{e(w.get("note", ""))}</div>{cites_html([w["syllabus"]])}')
    h.append(f'<p class="oneline">{prose(s["one_line"])}</p>')
    for kind, label in KIND:
        pts = [p for p in s.get("points", []) if p["kind"] == kind]
        if not pts: continue
        h.append(f"<h3>{label}</h3><ol class='pts'>")
        for p in pts:
            h.append(f"<li><p>{prose(p['text'])}</p>{cites_html(p['cites'])}</li>")
        h.append("</ol>")
    for ex in s.get("examples", []):
        h.append('<div class="ex"><h3>Worked example</h3>')
        h.append(f'<p class="q"><b>{e(ex["ref"])} [{ex["marks"]} marks]</b> “{e(ex["question"]["quote"])}”'
                 f'<span class="src"> {e(source(ex["question"]))}</span></p>')
        if ex.get("context"): h.append(f'<p class="ctx">{prose(ex["context"])}</p>')
        h.append('<p class="lbl good">A full-mark answer, built from the mark scheme (not a real candidate’s):</p><ol class="strong">')
        for st in ex["strong"]:
            h.append(f'<li>{prose(st["sentence"])}<div class="earns">earns: “{e(st["earns"]["quote"])}”'
                     f'<span class="src"> {e(source(st["earns"]))}</span></div></li>')
        h.append("</ol>")
        wk = ex.get("weak")
        if wk:
            h.append(f'<p class="lbl bad">A weak answer of the kind the examiners describe (written for this guide; likely {e(wk["marks_likely"])}):</p>'
                     f'<p class="weak">{prose(wk["answer"])}</p><p class="why">{prose(wk["why"])}</p>{cites_html([wk["basis"]])}')
        if ex.get("note"): h.append(f'<p class="note">{prose(ex["note"])}</p>')
        h.append("</div>")
    if s.get("thin_evidence"):
        h.append(f'<p class="thin"><b>How much evidence:</b> {prose(s["thin_evidence"])}</p>')
    h.append("</section>")
    return "".join(h)

SYLLABUS = {  # syllabus 2025-2027 p. 66, verbatim (checked by cw_verify on the _general section)
    "Analyse": "examine in detail to show meaning, identify elements and the relationship between them",
    "Assess": "make an informed judgement",
    "Compare": "identify/comment on similarities and/or differences",
    "Contrast": "identify/comment on differences",
    "Define": "give precise meaning",
    "Describe": "state the points of a topic/give characteristics and main features",
    "Discuss": "write about issue(s) or topic(s) in depth in a structured way",
    "Evaluate": "judge or calculate the quality, importance, amount, or value of something",
    "Explain": "set out purposes or reasons/make the relationships between things clear/say why and/or how and support with relevant evidence",
    "Identify": "name/select/recognise",
    "Justify": "support a case with evidence/argument",
    "State": "express in clear terms",
    "Suggest": "apply knowledge and understanding to situations where there are a range of valid responses in order to make proposals/put forward considerations",
}

CSS = """
:root{--ink:#1b1f24;--mute:#5d6670;--teal:#0f6466;--tint:#e3efef;--warn:#b5541c;--good:#2c7a4b}
*{box-sizing:border-box} body{font:10.5pt/1.45 Helvetica,Arial,sans-serif;color:var(--ink);margin:0 56px;background:#fff}
h1{font-size:30pt;margin:0 0 4px;letter-spacing:-.5px} h2{font-size:19pt;margin:0 0 8px;color:var(--ink);border-bottom:3px solid var(--teal);padding-bottom:4px;display:inline-block}
h3{font-size:11.5pt;color:var(--teal);margin:16px 0 6px;text-transform:uppercase;letter-spacing:.5px}
.kicker{color:var(--teal);font-weight:bold;font-size:9pt;letter-spacing:1px;margin-top:40px}
.sub{color:var(--mute);font-size:12pt;margin-bottom:18px}
section{break-before:auto;margin-top:34px} section.page{break-before:page;margin-top:0} section.first{margin-top:0}
h2,h3,.def,.oneline,.q,.lbl{break-after:avoid} .cite,.earns,.weak,tr{break-inside:avoid}
.oneline{background:var(--tint);border-left:4px solid var(--teal);padding:8px 12px;font-size:11.5pt;font-weight:bold;margin:10px 0}
.def{margin:6px 0} .src{color:var(--mute);font-size:8.3pt;font-style:normal;white-space:nowrap}
.cite{color:#3c4650;font-size:8.8pt;font-style:italic;margin:3px 0 0 0;padding-left:10px;border-left:2px solid #c9d6d6}
ol.pts{padding-left:20px} ol.pts li{margin-bottom:9px} ol.pts li>p{break-after:avoid} ol.pts p{margin:0}
.ex{border:1px solid #cfdcdc;border-radius:6px;padding:10px 14px;margin:14px 0;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.ex h3{margin-top:0} .q{margin:4px 0} .ctx{color:var(--mute);margin:4px 0}
.lbl{font-weight:bold;margin:8px 0 2px;font-size:9.5pt} .good{color:var(--good)} .bad{color:var(--warn)}
ol.strong{margin:0;padding-left:20px} ol.strong li{margin-bottom:5px}
.earns{color:var(--mute);font-size:8.5pt;font-style:italic}
.weak{background:#fbf1ea;padding:6px 10px;margin:2px 0;border-radius:4px} .why{margin:4px 0}
.note{margin-top:8px;font-weight:bold}
.thin{color:var(--mute);font-size:9pt;border-top:1px dashed #ccc;padding-top:6px;margin-top:14px}
table{border-collapse:collapse;width:100%;font-size:9.4pt;margin:8px 0} th{text-align:left;color:var(--mute);font-weight:normal;border-bottom:1px solid #bbb;padding:4px 6px}
td{border-bottom:1px solid #eee;padding:4px 6px;vertical-align:top} td.n{text-align:right;white-space:nowrap}
.bar{height:9px;background:var(--teal);border-radius:3px;display:inline-block;vertical-align:middle}
.myth{border:2px solid var(--warn);border-radius:6px;padding:10px 14px;margin:14px 0;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.myth h3{color:var(--warn);margin-top:0}
.small{font-size:9pt;color:var(--mute)}
table.glance td{padding:7px 6px;font-size:10pt} table.glance td:first-child{width:34%}
"""

def build():
    global COMP
    COMP = er_components()
    import cw_verify
    docs = cw_verify.load()
    for w, q in SYLLABUS.items():
        if cw_verify.find(docs, "9626_syllabus_2025-2027", q)[0] != 66:
            sys.exit(f"syllabus definition of {w} does not match p. 66")
    secs = {p.stem: json.loads(p.read_text()) for p in SEC.glob("*.json")}
    mk, n, tot, papers, parts = stats()
    syl = {w: {"syllabus": {"doc": "9626_syllabus_2025-2027", "quote": q, "page": 66}} for w, q in SYLLABUS.items()}
    g = secs["_general"]
    h = [f"<!doctype html><html><head><meta charset='utf-8'><title>Command words</title><style>{CSS}</style></head><body>"]
    h.append('<section class="first"><div class="kicker">CAIE 9626 · INFORMATION TECHNOLOGY · PAPERS 1 AND 3</div>'
             '<h1>Command words</h1><div class="sub">What each one asks for, how the marks are given, and what the examiners say goes wrong</div>')
    h.append(f'<p class="oneline">{prose(g["one_line"])}</p>')
    # share-of-marks table
    h.append(f"<h3>Which words carry the marks</h3><p class='small'>Every Paper 1 and Paper 3 question part from 2022 to March 2026: "
             f"{parts} parts in {papers} papers. Each part counts under the command word it uses.</p><table><tr><th>Word</th><th>Cambridge’s definition (syllabus p. 66)</th><th class='n'>Parts</th><th class='n'>Share of marks</th><th></th></tr>")
    top = max(mk.values())
    for w, v in mk.most_common():
        if w == "none" or v / tot < 0.004: continue
        d = syl.get(w)
        h.append(f"<tr><td><b>{e(w)}</b></td><td>{e(d['syllabus']['quote']) if d else '<span class=small>not in the syllabus list; an instruction, not a command word</span>'}</td>"
                 f"<td class='n'>{n[w]}</td><td class='n'>{100*v/tot:.1f}%</td><td><span class='bar' style='width:{80*v/top:.0f}px'></span></td></tr>")
    h.append("</table>")
    # the myth box: format points
    h.append('<div class="myth"><h3>“Write everything in bullet points” is wrong</h3><ol class="pts">')
    for p in [p for p in g["points"] if p["kind"] == "format"]:
        h.append(f"<li><p>{prose(p['text'])}</p>{cites_html(p['cites'])}</li>")
    h.append("</ol></div></section>")
    h.append('<section><h2>How the marks are given</h2><ol class="pts">')
    for p in [p for p in g["points"] if p["kind"] != "format"]:
        h.append(f"<li><p>{prose(p['text'])}</p>{cites_html(p['cites'])}</li>")
    h.append("</ol></section>")
    h.append('<section><h2>The words at a glance</h2><table class="glance"><tr><th>Command word</th><th>What to do</th></tr>')
    for k in ORDER:
        if k in secs:
            h.append(f"<tr><td><b>{e(TITLES.get(k, k))}</b></td><td>{prose(secs[k]['one_line'])}</td></tr>")
    h.append("</table></section>")
    for k in ORDER:
        if k in secs: h.append(section_html(secs[k], TITLES.get(k, k)))
    h.append(method_html(secs))
    h.append("</body></html>")
    OUT.mkdir(exist_ok=True)
    src = OUT / "command_words.html"
    src.write_text("".join(h))
    pdf = OUT / "Command words - what the examiners want.pdf"
    subprocess.run(["node", str(ROOT / "cw_pdf.js"), str(src), str(pdf)], check=True)
    print("wrote", pdf.relative_to(ROOT))

def method_html(secs):
    docs = Counter()
    for s in secs.values():
        for c in _cites(s): docs[c["doc"]] += 1
    nq = sum(docs.values())
    return ("<section class=\"page\"><h2>Where this comes from</h2>"
            f"<p>Every statement in this guide is followed by the words it rests on, copied from a Cambridge document, with the page. "
            f"There are {nq} quotations from {len(docs)} documents: the 9626 syllabus for 2025 to 2027, the Cambridge Learner Guide for 9626, "
            "and the question papers, mark schemes and examiner reports for Papers 1 and 3 from 2017 to March 2026. "
            "A script checked each quotation word for word against the document it cites and wrote in the page number it found; "
            "the guide will not build if any quotation fails that check.</p>"
            "<p>The worked examples use real questions. The full-mark answers were written for this guide by joining mark scheme points "
            "into sentences, and each sentence shows the mark scheme point it earns. The weak answers were also written for this guide, "
            "to show a mistake an examiner report describes. Neither is a real candidate’s work.</p>"
            "<p>What is not here: Cambridge’s Example Candidate Responses booklets for 9626 (real scripts with examiner comments). "
            "They are on the School Support Hub, which needs a teacher login, so this guide does not quote them.</p>"
            "<p>Limits: the share of marks per command word comes from automatic reading of the question papers. A part with no command word "
            "of its own counts under the word of the part before it. Papers 2 and 4 (practical) are not included.</p></section>")

def _cites(o):
    if isinstance(o, dict):
        if "doc" in o and "quote" in o: yield o
        for v in o.values(): yield from _cites(v)
    elif isinstance(o, list):
        for v in o: yield from _cites(v)

if __name__ == "__main__":
    build()
