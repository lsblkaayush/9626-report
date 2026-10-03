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
def straight(t):
    """Straight quotes and apostrophes throughout. Cambridge's curly marks inside a quotation
    become straight ones too; cw_verify.norm treats them as equal, so the words are unchanged."""
    return t.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")

def e(t):
    return html.escape(straight(t))

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
    return html.escape(straight(t))

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

def point_html(p):
    """A numbered point: its text and first quotation stay on one page, the rest may follow."""
    first, rest = p["cites"][:1], p["cites"][1:]
    return (f"<li><div class='lead'><p>{prose(p['text'])}</p>{cites_html(first)}</div>"
            f"{cites_html(rest, 'more')}</li>")

def cites_html(cites, cls=""):
    out = []
    for c in cites:
        out.append(f'<div class="cite"><span class="qt">"{e(c["quote"].strip())}"</span> <span class="src">{e(source(c))}</span></div>')
    return f'<div class="cites {cls}">{"".join(out)}</div>' if out else ""

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
    h = [f'<section class="word{" page" if title.startswith("Describe") else ""}"><div class="sechead"><h2>{e(title)}</h2>']
    for w in s.get("words", []):
        if not w.get("syllabus"):
            h.append(f'<div class="def"><b>{e(w["word"])}</b>: not in the syllabus list of command words. {e(w.get("note", ""))}</div>')
            continue
        q = SYLLABUS.get(w["word"])
        if q:
            h.append(f'<div class="def"><b>{e(w["word"])}</b>. Cambridge&#39;s definition: &quot;{e(q)}&quot;'
                     f' <span class="src">Syllabus 2025 to 2027, p. 66</span></div>')
        else:
            h.append(f'<div class="def"><b>{e(w["word"])}</b>: not in the syllabus table of command words. '
                     f'{e(w.get("note", ""))}</div>{cites_html([w["syllabus"]])}')
    h.append(f'<p class="oneline">{prose(s["one_line"])}</p></div>')
    for kind, label in KIND:
        pts = [p for p in s.get("points", []) if p["kind"] == kind]
        if not pts: continue
        h.append(f"<h3>{label}</h3><ol class='pts'>")
        for p in pts:
            h.append(point_html(p))
        h.append("</ol>")
    for ex in s.get("examples", []):
        h.append('<div class="ex"><div class="exhead"><h3>Worked example</h3>')
        h.append(f'<p class="q"><b>{e(ex["ref"])} [{ex["marks"]} marks]</b> "{e(ex["question"]["quote"])}"'
                 f' <span class="src">{e(source(ex["question"]))}</span></p>')
        if ex.get("context"): h.append(f'<p class="ctx">{prose(ex["context"])}</p>')
        # a short full-mark answer stays in one piece; a long one may break between its sentences
        h.append(f'</div><div class="{"strongblk" if len(ex["strong"]) <= 5 else "stronglong"}"><p class="lbl good">A full-mark answer, built from the mark scheme (not a real candidate&#39;s):</p><ol class="strong">')
        for st in ex["strong"]:
            h.append(f'<li>{prose(st["sentence"])}<div class="earns"><span class="k">earns:</span> "{e(st["earns"]["quote"])}"'
                     f' <span class="src">{e(source(st["earns"]))}</span></div></li>')
        h.append("</ol>")
        # the closing note shares a block with the answer just above it, so it never sits alone
        wk = ex.get("weak")
        if wk:
            h.append(f'</div><div class="weakblk"><p class="lbl bad">A weak answer of the kind the examiners describe (written for this guide; likely {e(wk["marks_likely"])}):</p>'
                     f'<p class="weak">{prose(wk["answer"])}</p><p class="why">{prose(wk["why"])}</p>{cites_html([wk["basis"]])}')
        if ex.get("note"): h.append(f'<p class="note">{prose(ex["note"])}</p>')
        h.append("</div></div>")
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
:root{--ink:#1b1f24;--mute:#545d66;--quote:#38424c;--teal:#0f6466;--tint:#e6f0f0;--rule:#c4d6d6;--warn:#b5541c;--good:#2c7a4b}
*{box-sizing:border-box} body{font:10.5pt/1.5 Helvetica,Arial,sans-serif;color:var(--ink);margin:0 60px;background:#fff;orphans:3;widows:3}
h1{font-size:30pt;margin:0 0 6px;letter-spacing:-.5px;line-height:1.15}
h2{font-size:20pt;line-height:1.2;margin:0 0 14px;color:var(--ink);border-bottom:3px solid var(--teal);padding-bottom:5px;display:inline-block}
h3{font-size:11pt;line-height:1.3;color:var(--teal);margin:24px 0 10px;text-transform:uppercase;letter-spacing:.6px}
.kicker{color:var(--teal);font-weight:bold;font-size:9pt;letter-spacing:1px;margin-top:6px}
.sub{color:var(--mute);font-size:12.5pt;line-height:1.4;margin-bottom:20px}
section{break-before:auto;margin-top:44px} .sechead{break-inside:avoid;break-after:avoid} section.page{break-before:page;margin-top:0} section.first{margin-top:0}
h2,h3,.def,.oneline,.lbl,.exhead,.weak{break-after:avoid}
.cite,.earns,.weak,.why,tr,ol.strong>li,.exhead,.strongblk,.weakblk,.note,.thin{break-inside:avoid}
.oneline{background:var(--tint);border-left:4px solid var(--teal);padding:10px 14px;font-size:11.5pt;line-height:1.45;font-weight:bold;margin:14px 0 4px}
.def{margin:0 0 4px;line-height:1.5} .sechead .cites{margin:5px 0 12px}
.src{color:var(--mute);font-size:8.5pt;font-style:normal;letter-spacing:.1px;white-space:nowrap}
.cites{margin:7px 0 0}
.cite{color:var(--quote);font-size:9pt;line-height:1.4;font-style:italic;padding:2px 0 3px 12px;border-left:2px solid var(--rule)}
.cite+.cite,.cites.more .cite{padding-top:4px} .cites.more{margin:0} .lead{break-inside:avoid}
ol.pts{padding-left:22px;margin:0} ol.pts>li{margin-bottom:14px;padding-left:2px} ol.pts>li:last-child{margin-bottom:4px}
ol.pts li>p{break-after:avoid} ol.pts p{margin:0}
.ex{border:1px solid #cddbdb;border-radius:6px;padding:14px 18px 12px;margin:24px 0;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.ex h3{margin:0 0 8px} .q{margin:0 0 4px} .ctx{color:var(--mute);margin:6px 0 0}
.lbl{font-weight:bold;margin:16px 0 6px;font-size:10pt;line-height:1.35} .good{color:var(--good)} .bad{color:var(--warn)}
ol.strong{margin:0;padding-left:22px} ol.strong>li{margin-bottom:10px}
.earns{color:var(--quote);font-size:9pt;line-height:1.4;font-style:italic;margin-top:2px}
.earns .k{font-style:normal;font-weight:bold;color:var(--good);font-size:8.5pt;text-transform:uppercase;letter-spacing:.5px}
.weakblk{margin-top:6px}
.weak{background:#fbf1ea;padding:8px 12px;margin:0 0 8px;border-radius:4px} .why{margin:0}
.note{margin:16px 0 4px;padding:2px 0 2px 12px;border-left:3px solid var(--teal);color:#123f40}
.thin{color:var(--mute);font-size:9.5pt;line-height:1.5;border-top:1px dashed #c8c8c8;padding-top:10px;margin-top:22px}
table{border-collapse:collapse;width:100%;font-size:9.8pt;line-height:1.4;margin:10px 0 4px}
th{text-align:left;color:var(--mute);font-weight:normal;border-bottom:1px solid #b5b5b5;padding:5px 8px;white-space:nowrap;vertical-align:bottom}
td{border-bottom:1px solid #e6e6e6;padding:5px 8px;vertical-align:top} td.n,th.n{text-align:right;white-space:nowrap}
.bar{height:9px;background:var(--teal);border-radius:3px;display:inline-block;vertical-align:middle}
.myth{border:2px solid var(--warn);border-radius:6px;padding:14px 18px 10px;margin:20px 0 0;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.myth h3{color:var(--warn);margin-top:0}
.small{font-size:9.5pt;color:var(--mute);line-height:1.45}
table.glance td{padding:9px 8px;font-size:10.5pt;line-height:1.45} table.glance td:first-child{width:32%}
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
             f"{parts} parts in {papers} papers. Each part counts under the command word it uses.</p><table><tr><th>Word</th><th>Cambridge's definition (syllabus p. 66)</th><th class='n'>Parts</th><th class='n'>Share of marks</th><th></th></tr>")
    top = max(mk.values())
    for w, v in mk.most_common():
        if w == "none" or v / tot < 0.004: continue
        d = syl.get(w)
        h.append(f"<tr><td><b>{e(w)}</b></td><td>{e(d['syllabus']['quote']) if d else '<span class=small>not in the syllabus list; an instruction, not a command word</span>'}</td>"
                 f"<td class='n'>{n[w]}</td><td class='n'>{100*v/tot:.1f}%</td><td><span class='bar' style='width:{80*v/top:.0f}px'></span></td></tr>")
    h.append("</table>")
    # the myth box: format points
    h.append('<div class="myth"><h3>"Write everything in bullet points" is wrong</h3><ol class="pts">')
    for p in [p for p in g["points"] if p["kind"] == "format"]:
        h.append(point_html(p))
    h.append("</ol></div></section>")
    h.append('<section><h2>How the marks are given</h2><ol class="pts">')
    for p in [p for p in g["points"] if p["kind"] != "format"]:
        h.append(point_html(p))
    h.append("</ol></section>")
    h.append('<section class="page"><h2>The words at a glance</h2><table class="glance"><tr><th>Command word</th><th>What to do</th></tr>')
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
            "to show a mistake an examiner report describes. Neither is a real candidate's work.</p>"
            "<p>What is not here: Cambridge's Example Candidate Responses booklets for 9626 (real scripts with examiner comments). "
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
