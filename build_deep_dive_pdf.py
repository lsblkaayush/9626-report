"""Reports/Paper N - Practical Deep Dive.pdf

One level below the paper reports: inside each subtopic, the individual actions the
mark schemes reward, and how many of the 2022+ papers asked for each one.

Data: data/deep_dive_p<N>.json. Each action carries refs ("s24 1(c)"), one per mark.
Paper counts and mark totals are derived here, never typed in by hand.

Builds an HTML page with inline SVG charts, then prints it to PDF with headless
Chromium (the Playwright copy in ~/.cache/ms-playwright). Pass --html to keep the
HTML next to the PDF for a quick look in a browser.

Look: plain white pages in the house teal, like the paper reports (build_report_pdf).
Text rules: ASD-STE100 style. Short sentences, active voice, one instruction per
sentence, no dashes. The data file text follows the same rules.
"""
import glob
import html
import json
import os
import re
import string
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_stats import COMPONENTS, SEASON_NAME, stated_total  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Reports"
THRESHOLDS = ROOT / "data" / "grade_thresholds.json"   # paper max per sitting
KIND = {"2": ("Practical", "AS Level"), "4": ("Advanced Practical", "A Level")}
MONTH = {"m": "Mar", "s": "Jun", "w": "Nov"}

# Every rule and size the pages print comes from these constants (never typed in the copy).
CORE_MIN = 2            # Core and Regular: asked in at least this many papers
CORE_SHARE = 0.5        # Core: asked in at least this share of the papers that had its topic
TOP_N = 15              # rows in "The N actions asked most often"
PARETO_MARKS = (20, 50, 100)   # points marked on the "learn first" curve
PARETO_HEADLINE = 50    # the point the takeaway sentence quotes

# House teal (build_report_pdf ACCENT = #0b6261) as a light-to-dark sequential ramp.
RAMP = ["#e4f2f0", "#cfe8e5", "#b6dcd8", "#9ccfca", "#81c1bb", "#65b2ab", "#4aa29b",
        "#33918a", "#1f8079", "#11706a", "#0b6261", "#08514f", "#06403f"]
ACCENT = RAMP[10]
TIER = {"core": ("Core", ACCENT, "#fff"), "regular": ("Regular", RAMP[2], "#0f2f2e"),
        "rare": ("Rare", "#e6e7ea", "#333")}
INK, INK2, MUTED, RULE = "#16191f", "#4a4f59", "#5c626d", "#dfe1e5"

e = html.escape


def load(paper, src=None):
    d = json.loads((src or ROOT / "data" / f"deep_dive_p{paper}.json").read_text())
    order = d["sittings"]
    bad = []
    for ch in d["chapters"]:
        ch["per"] = {}
        for st in ch["subtopics"]:
            for a in st["actions"]:
                sess = [r.split()[0] for r in a["refs"]]
                bad += [f"{a['action']}: {r}" for r in a["refs"] if r.split()[0] not in order]
                a["sittings"] = sorted(set(sess) & set(order), key=order.index)
                a["marks"] = len(a["refs"])
                for s in sess:
                    ch["per"][s] = ch["per"].get(s, 0) + 1
            st["actions"] = [a for a in st["actions"] if a["sittings"]]
            st["marks"] = sum(a["marks"] for a in st["actions"])
            st["sittings"] = sorted({s for a in st["actions"] for s in a["sittings"]},
                                    key=order.index)
        ch["subtopics"] = [s for s in ch["subtopics"] if s["actions"]]
        ch["subtopics"].sort(key=lambda s: -s["marks"])
        ch["marks"] = sum(s["marks"] for s in ch["subtopics"])
        ch["sittings"] = sorted({s for st in ch["subtopics"] for s in st["sittings"]},
                                key=order.index)
        for st in ch["subtopics"]:
            for a in st["actions"]:
                a["of"] = ch["sittings"]
                a["chapter"] = ch["name"]
                a["tier"] = tier(a)
            st["actions"].sort(key=rank)
    if bad:
        print(f"warning: {len(bad)} refs outside {order[0]}..{order[-1]}:", *bad[:10],
              sep="\n  ", file=sys.stderr)
    d["chapters"].sort(key=lambda c: -c["marks"])
    d["marks"] = sum(c["marks"] for c in d["chapters"])
    d["actions"] = [a for c in d["chapters"] for s in c["subtopics"] for a in s["actions"]]
    d["totals"] = {s: sum(c["per"].get(s, 0) for c in d["chapters"]) for s in order}
    d["max"] = paper_max(d["paper"], order)
    check_summaries(d)
    return d


def paper_max(paper, order):
    """Marks of the paper per sitting, from grade_thresholds.json. Refuses to build when a
    sitting is missing or disagrees with report_stats.stated_total (the second source)."""
    gt = json.loads(Path(THRESHOLDS).read_text())
    out = {}
    for s in order:
        (code,) = COMPONENTS[paper]          # practical papers have one component
        comp = gt.get(s, {}).get("components", {}).get(code)
        if comp is None:
            raise ValueError(f"{Path(THRESHOLDS).name}: no component {code} for {s}")
        want = stated_total(2000 + int(s[1:]), paper)
        if comp["max"] != want:
            raise ValueError(f"{s} paper {paper}: max {comp['max']} in {Path(THRESHOLDS).name} "
                             f"!= report_stats.stated_total {want}")
        out[s] = comp["max"]
    return out


# Why a column does not add up to the marks of the paper. Read from the data file's notes:
#   capped parts:  "<s> <task> <part> (<bullets> bullets, <marks> marks)"
#   exclusions:    "Excluded: <s> <questions> (<marks> marks, <what>)"
CAPPED_PART = r"\b{s} ([^()]*?\([a-z]\) \d\([a-z]\)) \((\d+) bullets, (\d+) marks?\)"
EXCLUDED = r"Excluded: {s} [^(]*\((\d+) marks?, ([^)]*)\)"


def off_reason(d, s):
    """Reason for column s, or None. The numbers in it are checked against the column."""
    t, mx, notes = d["totals"][s], d["max"][s], d.get("notes", "")
    if t > mx:
        parts = re.findall(CAPPED_PART.format(s=re.escape(s)), notes)
        if not parts:
            return None
        extra = sum(int(b) - int(m) for _, b, m in parts)
        if extra != t - mx:
            raise ValueError(f"P{d['paper']} {s}: notes' capped parts add {extra} marks, "
                             f"column is {t - mx} over {mx}")
        capped_refs = {r for a in d["actions"] if a.get("capped") for r in a["refs"]}
        lost = [f"{s} {p}" for p, _, _ in parts if f"{s} {p}" not in capped_refs]
        if lost:
            raise ValueError(f"P{d['paper']}: notes name capped parts {lost} that no capped action holds")
        return (f"{len(parts)} parts of its mark scheme list more points than the marks they "
                f"give, and every point is counted")
    m = re.search(EXCLUDED.format(s=re.escape(s)), notes)
    if not m:
        return None
    if int(m.group(1)) != mx - t:
        raise ValueError(f"P{d['paper']} {s}: notes exclude {m.group(1)} marks, column is "
                         f"{mx - t} under {mx}")
    return f"{mx - t} of its marks are for {m.group(2)}, which is not in these topics"


def listed(codes, word="and"):
    """'s22', 's22 and w24', 's22, w24 and s25' (word='or' for 'not s22, s24 or s25')."""
    if not codes:
        raise ValueError("empty list of papers in a summary")
    return codes[0] if len(codes) == 1 else ", ".join(codes[:-1]) + f" {word} " + codes[-1]


def n_papers(k):
    return f"{k} paper" + ("" if k == 1 else "s")


def span(vals):
    """'10 to 12', or '10' when every value is the same."""
    lo, hi = min(vals), max(vals)
    return f"{lo}" if lo == hi else f"{lo} to {hi}"


# Summaries in data/deep_dive_p<N>.json are templates: every count, sitting list and mark range is a
# {field} filled here from the refs, never typed in the JSON (lint: phase5/lint_numbers.py). A ref is
# '<sitting> <task>[(part)...]': the task is the question number, a part is a lettered sub-question.
#   both levels      {n} papers it came up in; {n_papers} the same as 'N paper(s)'; {total} papers in the
#                    data; {papers} its sittings ('s22, w24 and s25'); {paper_max} marks of the paper
#                    (refused unless every sitting has the same maximum)
#   chapter only     {not_and} / {not_or} the sittings without the chapter (refused when there are none)
#   subtopic only    {in_chapter} papers that had the chapter; {papers_times} like {papers}, with
#                    '(2 times)' after a sitting with two tasks; {task_marks} range of the marks per task
#                    (one sitting, one question number); {part_marks_or} the distinct marks per lettered
#                    part ('3 or 4': from m24 on, each relationship is its own part);
#                    {action_n:<action>} / {action_n_papers:<action>} papers that asked that action
# Any other field, a field of the wrong level, or an unknown action stops the build.
CHAPTER_FIELDS = {"n", "n_papers", "total", "papers", "paper_max", "not_and", "not_or"}
SUBTOPIC_FIELDS = {"n", "n_papers", "total", "papers", "paper_max", "in_chapter", "papers_times",
                   "task_marks", "part_marks_or", "action_n", "action_n_papers"}
ACTION_FIELDS = {"action_n", "action_n_papers"}


def split_ref(r):
    s, rest = r.split(" ", 1)
    return s, rest.split("(")[0], rest if "(" in rest else None


def summary_values(d, c, st=None):
    """Value of each field for chapter c (st=None) or for its subtopic st. Refs outside the sittings are
    already dropped from the counts (load() warns about them)."""
    order = d["sittings"]
    maxima = set(d["max"].values())
    v = {"total": lambda: len(order),
         "paper_max": lambda: (maxima.pop() if len(maxima) == 1 else (_ for _ in ()).throw(
             ValueError(f"P{d['paper']}: paper maxima differ by sitting {sorted(maxima)}; "
                        f"a summary cannot print one")))}
    item = st or c
    v["n"] = lambda: len(item["sittings"])
    v["n_papers"] = lambda: n_papers(len(item["sittings"]))
    v["papers"] = lambda: listed(item["sittings"])
    if st is None:
        rest = [s for s in order if s not in c["sittings"]]
        v["not_and"] = lambda: listed(rest, "and")
        v["not_or"] = lambda: listed(rest, "or")
        return v
    refs = [split_ref(r) for a in st["actions"] for r in a["refs"] if r.split()[0] in order]
    task, part = {}, {}
    for s, t, p in refs:
        task[(s, t)] = task.get((s, t), 0) + 1
        if p:
            part[(s, p)] = part.get((s, p), 0) + 1
    times = {s: sum(1 for (s2, _) in task if s2 == s) for s in st["sittings"]}
    v["in_chapter"] = lambda: len(c["sittings"])
    v["papers_times"] = lambda: listed([s + (f" ({times[s]} times)" if times[s] > 1 else "")
                                        for s in st["sittings"]])
    v["task_marks"] = lambda: span(task.values())
    v["part_marks_or"] = lambda: listed([str(m) for m in sorted(set(part.values()))], "or")
    return v


def render_summary(d, c, st=None):
    item = st or c
    text = item.get("summary", "")
    allowed = CHAPTER_FIELDS if st is None else SUBTOPIC_FIELDS
    where = f"P{d['paper']} {c['name']}" + (f" / {st['name']}" if st else "")
    try:
        parts = list(string.Formatter().parse(text))
    except ValueError as ex:
        raise ValueError(f"{where}: summary is not a valid template ({ex}): {text!r}") from None
    values = summary_values(d, c, st)
    out = []
    for lit, field, spec, conv in parts:
        out.append(lit)
        if field is None:
            continue
        if field not in allowed or conv:
            raise ValueError(f"{where}: summary field {{{field}}} is not one of {sorted(allowed)}")
        if field in ACTION_FIELDS:
            a = next((a for a in st["actions"] if a["action"] == spec), None)
            if a is None:
                raise ValueError(f"{where}: {{{field}:{spec}}} names no action of this subtopic")
            k = len(a["sittings"])
            out.append(n_papers(k) if field == "action_n_papers" else str(k))
            continue
        if spec:
            raise ValueError(f"{where}: summary field {{{field}:{spec}}} takes no format")
        out.append(str(values[field]()))
    item["summary"] = "".join(out)
    if "{" in item["summary"] or "}" in item["summary"]:
        raise ValueError(f"{where}: brace left in the rendered summary: {item['summary']!r}")


def check_summaries(d):
    """Fill the computed fields of every chapter and subtopic summary (see SUBTOPIC_FIELDS)."""
    for c in d["chapters"]:
        render_summary(d, c)
        for st in c["subtopics"]:
            render_summary(d, c, st)


def tier(a):
    n, of = len(a["sittings"]), len(a["of"])
    if n >= CORE_MIN and n >= of * CORE_SHARE:
        return "core"
    return "regular" if n >= CORE_MIN else "rare"


def rare_words():
    """'1 paper only' / '1 paper', or 'N papers or fewer' when CORE_MIN is above 2."""
    k = CORE_MIN - 1
    return (f"{k} paper only", f"{k} paper") if k == 1 else (f"{k} papers or fewer",) * 2


def rank(a):
    """Most papers first, then most marks. Absolute counts, so a topic that came up
    4 times cannot outrank one that came up 9 times on a 4/4 ratio alone."""
    return (["core", "regular", "rare"].index(a["tier"]), -len(a["sittings"]), -a["marks"])


def sess_label(s):
    return f"{MONTH[s[0]]} 20{s[1:]}"


# ---------------------------------------------------------------- small pieces

R, GAP, YGAP = 4.3, 3.4, 9


def _x(i):
    return R + 1 + i * (2 * R + GAP) + (i // 3) * YGAP


def _w(order):
    return _x(len(order) - 1) + R + 1


def mark(kind, cx, cy):
    """Filled = asked. Ring = topic in that paper, action not asked.
    Short grey dash = topic not in that paper, so it could not be asked."""
    if kind == "hit":
        return f'<circle cx="{cx:.1f}" cy="{cy}" r="{R}" fill="{ACCENT}"/>'
    if kind == "ring":
        return (f'<circle cx="{cx:.1f}" cy="{cy}" r="{R - 0.7}" fill="#fff" '
                f'stroke="{RAMP[5]}" stroke-width="1.4"/>')
    return (f'<line x1="{cx - 2.6:.1f}" x2="{cx + 2.6:.1f}" y1="{cy}" y2="{cy}" '
            f'stroke="#c3c6cc" stroke-width="1.6" stroke-linecap="round"/>')


def dots(order, hit, present):
    h = 2 * R + 2
    out = [f'<svg class="dots" width="{_w(order):.0f}" height="{h:.0f}" role="img" '
           f'aria-label="asked in {len(hit)} of {len(present)} papers">']
    for i, s in enumerate(order):
        out.append(mark("hit" if s in hit else "ring" if s in present else "none",
                        _x(i), R + 1))
    return "".join(out) + "</svg>"


def dots_head(order):
    out = [f'<svg class="dots" width="{_w(order):.0f}" height="11">']
    for y in range(len(order) // 3):
        x = (_x(3 * y) + _x(3 * y + 2)) / 2
        out.append(f'<text x="{x:.1f}" y="9" text-anchor="middle" font-size="8.5" '
                   f'font-weight="700" fill="{MUTED}">20{order[3 * y][1:]}</text>')
    return "".join(out) + "</svg>"


def key_mark(kind):
    return f'<svg width="11" height="11">{mark(kind, 5.5, 5.5)}</svg>'


def badge(t):
    name, bg, fg = TIER[t]
    return f'<span class="badge" style="background:{bg};color:{fg}">{name}</span>'


def asked(a):
    return f'<b>{len(a["sittings"])}</b> of {len(a["of"])}'


def total(a):
    """Printed total marks of an action. One string for every table that prints it (topic
    pages, top 15, checklist): '*' when the JSON entry is capped (legend '7*' on page 1)."""
    return f'{a["marks"]}' + ("*" if a.get("capped") else "")


def thead(order, first="Priority", width="50pt"):
    return (f'<thead><tr><th style="width:{width}">{first}</th><th>Action</th>'
            f'<th>{dots_head(order)}</th><th class="num">Asked in</th>'
            f'<th class="num">Total<br>marks</th></tr></thead>')


# ---------------------------------------------------------------- charts

def heatmap(d):
    """Chapters x papers, cell = marks in that paper. Dashed cell = not in the paper."""
    order = d["sittings"]
    lw, cw, ch_, top = 170, 33, 27, 34
    W, H = lw + cw * len(order) + 44, top + ch_ * len(d["chapters"]) + 4
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" width="100%" role="img" '
           f'aria-label="Marks per topic in each paper">']
    for i, s in enumerate(order):
        x = lw + i * cw + cw / 2
        out.append(f'<text x="{x}" y="25" text-anchor="middle" font-size="9" fill="{INK2}">'
                   f'{MONTH[s[0]]}</text>')
        if i % 3 == 0:
            out.append(f'<text x="{x + cw}" y="11" text-anchor="middle" font-size="9.5" '
                       f'font-weight="700" fill="{INK}">20{s[1:]}</text>')
            if i:
                out.append(f'<line x1="{lw + i * cw}" x2="{lw + i * cw}" y1="2" y2="{H}" '
                           f'stroke="{RULE}"/>')
    out.append(f'<text x="{W - 2}" y="25" text-anchor="end" font-size="9" '
               f'font-weight="700" fill="{INK}">papers</text>')
    for j, c in enumerate(d["chapters"]):
        y = top + j * ch_
        out.append(f'<text x="{lw - 10}" y="{y + ch_ / 2 + 3.5}" text-anchor="end" '
                   f'font-size="10.5" fill="{INK}">{e(c["name"])}</text>')
        for i, s in enumerate(order):
            m = c["per"].get(s, 0)
            x = lw + i * cw
            if not m:
                out.append(f'<rect x="{x + 2.5}" y="{y + 2.5}" width="{cw - 5}" '
                           f'height="{ch_ - 5}" rx="4" fill="none" stroke="#cdd0d5" '
                           f'stroke-dasharray="2 2"/>')
                continue
            k = min(len(RAMP) - 1, 1 + round(m / max(d["max"].values()) * (len(RAMP) - 2)))
            fg = "#fff" if k >= 6 else INK
            out.append(f'<rect x="{x + 2.5}" y="{y + 2.5}" width="{cw - 5}" height="{ch_ - 5}" '
                       f'rx="4" fill="{RAMP[k]}"/><text x="{x + cw / 2}" y="{y + ch_ / 2 + 3.5}" '
                       f'text-anchor="middle" font-size="10" font-weight="700" fill="{fg}">{m}'
                       f'</text>')
        out.append(f'<text x="{W - 2}" y="{y + ch_ / 2 + 3.5}" text-anchor="end" '
                   f'font-size="10.5" font-weight="700" fill="{INK}">{len(c["sittings"])}'
                   f'<tspan fill="{MUTED}" font-weight="400"> / {len(order)}</tspan></text>')
    return "".join(out) + "</svg>"


def hbars(rows, total, *, label_w=190, W=520, note_w=110):
    """rows: (label, value, note). Bar length = value, value printed at the bar end."""
    rh, track = 25, W - label_w - note_w - 70
    vmax = max(v for _, v, _ in rows) or 1
    out = [f'<svg class="chart" viewBox="0 0 {W} {rh * len(rows)}" width="100%" role="img">']
    for i, (lab, v, note) in enumerate(rows):
        y = i * rh
        bw = max(3, track * v / vmax)
        out.append(f'<text x="{label_w - 10}" y="{y + 15.5}" text-anchor="end" '
                   f'font-size="{10.5 if len(lab) <= 36 else 9}" fill="{INK}">{e(lab)}</text>'
                   f'<rect x="{label_w}" y="{y + 5.5}" width="{bw:.1f}" height="13" rx="3" '
                   f'fill="{ACCENT}"/>'
                   f'<text x="{label_w + bw + 6:.1f}" y="{y + 15.5}" font-size="10" '
                   f'font-weight="700" fill="{INK}">{v}<tspan font-weight="400" fill="{INK2}"> '
                   f'marks ({100 * v / total:.0f}%)</tspan></text>'
                   f'<text x="{W}" y="{y + 15.5}" text-anchor="end" font-size="9.5" '
                   f'fill="{MUTED}">{e(note)}</text>')
    return "".join(out) + "</svg>"


def pareto(d):
    """Cumulative share of all marks, actions sorted by marks. Answers: how far do
    the first N actions get you?"""
    ms = sorted((a["marks"] for a in d["actions"]), reverse=True)
    n, tot = len(ms), sum(ms)
    cum, run = [], 0
    for m in ms:
        run += m
        cum.append(100 * run / tot)
    W, H, l, b, t, r = 520, 200, 40, 30, 12, 12
    pw, ph = W - l - r, H - b - t
    X = lambda i: l + pw * i / n
    Y = lambda p: t + ph * (1 - p / 100)
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" width="100%" role="img" '
           f'aria-label="Share of marks covered by the top actions">']
    for p in (0, 25, 50, 75, 100):
        out.append(f'<line x1="{l}" x2="{W - r}" y1="{Y(p)}" y2="{Y(p)}" stroke="{RULE}"/>'
                   f'<text x="{l - 6}" y="{Y(p) + 3.5}" text-anchor="end" font-size="9" '
                   f'fill="{MUTED}">{p}%</text>')
    for i in range(0, n + 1, 25):
        out.append(f'<text x="{X(i)}" y="{H - b + 14}" text-anchor="middle" font-size="9" '
                   f'fill="{MUTED}">{i}</text>')
    out.append(f'<text x="{l + pw / 2}" y="{H - 3}" text-anchor="middle" font-size="9.5" '
               f'fill="{INK2}">number of actions you learn (most marks first)</text>')
    pts = " ".join(f"{X(i + 1):.1f},{Y(c):.1f}" for i, c in enumerate(cum))
    out.append(f'<polygon points="{X(0)},{Y(0)} {pts} {X(n)},{Y(0)}" fill="{RAMP[0]}"/>'
               f'<polyline points="{X(0)},{Y(0)} {pts}" fill="none" stroke="{ACCENT}" '
               f'stroke-width="2" stroke-linejoin="round"/>')
    marks = sorted(set(PARETO_MARKS) | {PARETO_HEADLINE})
    for k in marks:
        if k < n:
            c = cum[k - 1]
            out.append(f'<line x1="{X(k)}" x2="{X(k)}" y1="{Y(c)}" y2="{Y(0)}" '
                       f'stroke="{ACCENT}" stroke-dasharray="2 2"/>'
                       f'<circle cx="{X(k)}" cy="{Y(c)}" r="4" fill="{ACCENT}" '
                       f'stroke="#fff" stroke-width="2"/>'
                       f'<text x="{X(k) + 7}" y="{Y(c) + 14}" font-size="10" fill="{INK}">'
                       f'<tspan font-weight="700">{c:.0f}%</tspan> from {k}</text>')
    return "".join(out) + "</svg>", {k: cum[k - 1] for k in marks if k < n}


def tier_bar(d):
    """100% stacked bars: share of marks and share of actions per tier."""
    rows = []
    for key in ("core", "regular", "rare"):
        acts = [a for a in d["actions"] if a["tier"] == key]
        rows.append((key, len(acts), sum(a["marks"] for a in acts)))
    W, lw = 520, 60
    out = [f'<svg class="chart" viewBox="0 0 {W} 64" width="100%" role="img">']
    for j, (lab, idx) in enumerate((("marks", 2), ("actions", 1))):
        y, x = 4 + j * 32, lw
        tot = sum(r[idx] for r in rows)
        out.append(f'<text x="{lw - 8}" y="{y + 15}" text-anchor="end" font-size="10.5" '
                   f'fill="{INK}">{lab}</text>')
        for row in rows:
            w = (W - lw) * row[idx] / tot
            name, bg, fg = TIER[row[0]]
            out.append(f'<rect x="{x:.1f}" y="{y}" width="{max(w - 2, 1):.1f}" height="22" '
                       f'rx="3" fill="{bg}"/>')
            num = (f'{row[idx]} ({100 * row[idx] / tot:.0f}%)' if w > 120
                   else f'{100 * row[idx] / tot:.0f}%')
            out.append(f'<text x="{x + 7:.1f}" y="{y + 15}" font-size="10" fill="{fg}">'
                       f'<tspan font-weight="700">{name}</tspan> {num}</text>')
            x += w
    return "".join(out) + "</svg>", rows


# ---------------------------------------------------------------- pages

CSS = """
@page { size: A4; margin: 17mm 17mm 17mm 17mm;
  @top-left { content: "__RUNNING__"; font: 7.5pt 'Noto Sans', sans-serif; color: #8a8f99; }
  @bottom-right { content: counter(page); font: 8pt 'Noto Sans', sans-serif; color: #8a8f99; } }
@page first { margin-top: 0; @top-left { content: none } }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; font: 9.8pt/1.55 'Noto Sans', sans-serif; color: #16191f;
       font-variant-numeric: lining-nums tabular-nums; orphans: 3; widows: 3; }
h1, h2, h3 { font-weight: 700; letter-spacing: -0.01em; }
h1 { font-size: 21pt; line-height: 1.15; margin: 0 0 14pt; }
h1::after { content: ""; display: block; width: 26pt; height: 2.5pt; background: #0b6261; margin-top: 7pt; }
h3 { font-size: 11.5pt; margin: 0; }
p { margin: 0 0 8pt; }
b { font-weight: 700; }
.muted { color: #4a4f59; }
.kicker { font-weight: 700; font-size: 7.8pt; letter-spacing: .1em; text-transform: uppercase;
          color: #0b6261; margin-bottom: 4pt; }
.page { break-before: page; }
.takeaway { font-weight: 700; font-size: 10.5pt; margin: 0 0 6pt; }
.chart { display: block; margin: 6pt 0 4pt; }
.figure { break-inside: avoid; margin: 0 0 26pt; }
.caption { font-size: 8.6pt; color: #4a4f59; margin-top: 4pt; }

/* first page */
.first { page: first; padding-top: 17mm; }
.first .bar { height: 7pt; background: #0b6261; margin: 0 -17mm 22mm; }
.first h1.title { font-size: 40pt; margin: 2pt 0 4pt; } .first h1.title::after { display: none; }
.sub-title { font-size: 12pt; color: #4a4f59; margin-bottom: 16pt; }
.rule { border-top: 1px solid #dfe1e5; margin: 0 0 18pt; }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12pt; margin-bottom: 28pt; }
.tile { background: #f5f6f8; border-left: 3pt solid #0b6261; padding: 10pt 12pt; }
.tile .n { font-size: 20pt; font-weight: 700; line-height: 1.1; }
.tile .l { font-size: 8.6pt; color: #4a4f59; margin-top: 3pt; line-height: 1.35; }
.keyhead { font-weight: 700; font-size: 11.5pt; margin: 0 0 8pt; }
.anatomy { display: grid; grid-template-columns: 1.2fr auto 84pt 70pt; column-gap: 16pt; margin-bottom: 14pt; }
.anatomy .cell { padding: 8pt 0; border-top: 1.2px solid #16191f; border-bottom: 1px solid #dfe1e5; }
.anatomy .num { text-align: right; }
.anatomy .note { font-size: 8.6pt; color: #4a4f59; line-height: 1.35; padding-top: 6pt; }
.anatomy .note b { color: #0b6261; display: block; }
.keylist { display: grid; grid-template-columns: auto 1fr; gap: 6pt 10pt; align-items: center;
           font-size: 9pt; margin-bottom: 18pt; }
.keylist .k { display: flex; align-items: center; justify-content: flex-end; }
ol.steps { margin: 4pt 0 0; padding-left: 16pt; } ol.steps li { margin: 4pt 0; }
.small { font-size: 8.6pt; }

/* tables */
table { width: 100%; border-collapse: collapse; }
th { font-size: 8pt; font-weight: 700; color: #5c626d; text-align: left; padding: 0 8pt 5pt 0;
     border-bottom: 1.2px solid #16191f; vertical-align: bottom; line-height: 1.2; }
td { padding: 7pt 8pt 7pt 0; border-bottom: 1px solid #eceef1; vertical-align: top; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
td.num, th.num { text-align: right; white-space: nowrap; }
td.num:last-child, th.num:last-child { padding-right: 0; }
td.dot { padding-top: 8.5pt; white-space: nowrap; }
.act { font-weight: 600; }
.detail { display: block; font-size: 8.6pt; color: #4a4f59; font-weight: 400; margin-top: 2pt; }
.badge { display: inline-block; font-size: 7.4pt; font-weight: 700; border-radius: 99pt;
         padding: 1pt 7pt; white-space: nowrap; margin-top: 1.5pt; }
.ch { font-size: 8.4pt; color: #5c626d; }

/* topic opener */
.chhead { display: flex; justify-content: space-between; align-items: flex-end; gap: 16pt; margin-bottom: 12pt; }
.chhead h1 { margin: 0; }
.stats { display: flex; gap: 20pt; flex-shrink: 0; }
.stat .n { font-size: 16pt; font-weight: 700; line-height: 1; color: #0b6261; }
.stat .l { font-size: 8pt; color: #4a4f59; max-width: 76pt; line-height: 1.25; margin-top: 3pt; }

/* subtopic */
.sub { margin-top: 34pt; }
.keep { break-inside: avoid; break-after: avoid; }
.subhead { display: flex; justify-content: space-between; align-items: baseline; gap: 12pt;
           border-top: 2px solid #0b6261; padding-top: 8pt; margin-bottom: 6pt; }
.meta { font-size: 8.6pt; color: #4a4f59; white-space: nowrap; }
.notes { margin-top: 10pt; font-size: 9pt; }
.notes > div { margin-top: 7pt; break-inside: avoid; }
.lab { font-weight: 700; font-size: 7.6pt; letter-spacing: .08em; text-transform: uppercase; color: #0b6261;
       margin-right: 6pt; }
.notes ul { margin: 2pt 0 0; padding-left: 14pt; }
.notes li { margin: 1.5pt 0; }
.rare ul { columns: 2; column-gap: 20pt; color: #4a4f59; }
.rare li { break-inside: avoid; }
.sess { color: #5c626d; font-size: 8.2pt; }

.top td { padding-top: 5pt; padding-bottom: 5pt; }
/* checklist */
.check td:first-child { width: 18pt; }
.tick { display: inline-block; width: 9pt; height: 9pt; border: 1.2px solid #4a4f59; border-radius: 2pt; margin-top: 3pt; }
.group td { font-weight: 700; font-size: 10.5pt; padding-top: 16pt; border-bottom: 1.2px solid #16191f; }
"""


def first(d, kind, level):
    order = d["sittings"]
    core = [a for a in d["actions"] if a["tier"] == "core"]
    share = 100 * sum(a["marks"] for a in core) / d["marks"]
    # Example row: an action from a topic that missed some papers, so every mark shows.
    demo = next(a for a in sorted(d["actions"], key=rank)
                if len(a["of"]) < len(order) and len(a["sittings"]) < len(a["of"]))
    n, of = len(demo["sittings"]), len(demo["of"])
    pair = lambda a: (len(a["sittings"]), len(a["of"]))
    # Rule examples, both real rows of this paper: the Core row with the fewest papers, and
    # the non-Core row (asked in CORE_MIN or more) with the most papers.
    core_ex = min((pair(a) for a in core), key=lambda p: (p[0], -p[1]), default=None)
    reg_ex = max((pair(a) for a in d["actions"] if a["tier"] == "regular"), default=None)
    example = (f' So "{core_ex[0]} of {core_ex[1]}" is Core, but "{reg_ex[0]} of {reg_ex[1]}" '
               f'is not.' if core_ex and reg_ex else "")
    code = order[-1]   # paper-code example: the latest sitting
    key = ", ".join(f"{k} = {v}" for k, v in SEASON_NAME.items())
    capped = [a for a in d["actions"] if a.get("capped")]
    star = max(capped, key=lambda a: a["marks"]) if capped else None
    star_row = (f'<div class="k"><b>{total(star)}</b></div><div>The mark scheme lists more mark '
                f'lines than the question\n      gives marks.</div>' if star else "")
    rare_legend, _ = rare_words()
    return f"""
<section class="first">
  <div class="bar"></div>
  <div class="kicker">CAIE 9626 · Information Technology</div>
  <h1 class="title">Paper {d['paper']}</h1>
  <div class="sub-title">{kind} &nbsp;·&nbsp; action by action &nbsp;·&nbsp; {level}</div>
  <div class="rule"></div>
  <div class="tiles">
    <div class="tile"><div class="n">{len(order)}</div><div class="l">past papers, {sess_label(order[0])}
      to {sess_label(order[-1])}</div></div>
    <div class="tile"><div class="n">{len(d['actions'])}</div><div class="l">actions that the mark
      schemes give marks for</div></div>
    <div class="tile"><div class="n">{share:.0f}%</div><div class="l">of all marks come from the
      {len(core)} Core actions</div></div>
  </div>

  <div class="keyhead">How to read the tables</div>
  <div class="anatomy">
    <div class="cell"><span class="act">{e(demo['action'])}</span><br>{badge(demo['tier'])}</div>
    <div class="cell">{dots_head(order)}<br>{dots(order, demo['sittings'], demo['of'])}</div>
    <div class="cell num">{asked(demo)}</div>
    <div class="cell num"><b>{total(demo)}</b></div>
    <div class="note"><b>Action</b>One thing that the mark scheme gives marks for.</div>
    <div class="note"><b>One symbol for each paper</b>March, June and November of each year.</div>
    <div class="note"><b>Asked in</b>{of} papers had this topic. {n} of them asked for this.</div>
    <div class="note"><b>Total marks</b>All marks for this action in all {len(order)} papers.</div>
  </div>
  <div class="keylist">
    <div class="k">{key_mark('hit')}</div><div>The paper asked for this action.</div>
    <div class="k">{key_mark('ring')}</div><div>The topic was in the paper, but this action was not asked.</div>
    <div class="k">{key_mark('none')}</div><div>The topic was not in the paper.</div>
    <div class="k">{badge('core')}</div><div>Asked in {CORE_SHARE:.0%} or more of the papers that had its topic
      (and in {CORE_MIN} papers or more).{example}</div>
    <div class="k">{badge('regular')}</div><div>Asked in {CORE_MIN} papers or more.</div>
    <div class="k">{badge('rare')}</div><div>Asked in {rare_legend}.</div>
    <div class="k"><b>{code}</b></div><div>A paper code: {key}. So {code} is
      the {SEASON_NAME[code[0]]} 20{code[1:]} paper.</div>
    {star_row}
  </div>
  <div class="keyhead">Where to start</div>
  <ol class="steps">
    <li>Learn every Core action. The checklist at the end lists all of them.</li>
    <li>Do the past question named under "Practise" in each subtopic.</li>
    <li>Learn the Regular actions.</li>
    <li>Read the Rare actions last. They show what else can come.</li>
  </ol>
</section>"""


def total_note(d):
    """Caption sentences for every column that does not add up to the paper's marks."""
    out = []
    for s, t in d["totals"].items():
        if t == d["max"][s]:
            continue
        why = off_reason(d, s)
        out.append(f" The {sess_label(s)} column adds up to {t}, not {d['max'][s]}"
                   + (f", because {why}." if why else "."))
    if not out:
        return ""
    common = sorted(set(d["max"].values()))
    head = (f" Most columns add up to the {common[0]} marks of the paper." if len(common) == 1
            else " Most columns add up to the marks of their paper.")
    return head + "".join(out)


def overview(d):
    order = d["sittings"]
    big = d["chapters"][:2]
    svg_p, cov = pareto(d)
    svg_t, rows = tier_bar(d)
    core = rows[0]
    top = sorted(d["actions"], key=lambda a: (-len(a["sittings"]), -a["marks"]))[:TOP_N]
    # Ordering example from the table itself: its first row against its last row.
    hi, lo = len(top[0]["sittings"]), len(top[-1]["sittings"])
    order_ex = (f" An action asked in {hi} papers\n  comes before an action asked in {lo} papers."
                if hi > lo else "")
    avg = lambda c: c["marks"] / len(c["sittings"])
    trs = "".join(
        f'<tr><td class="num muted">{i}</td><td><span class="act">{e(a["action"])}</span>'
        f'<br><span class="ch">{e(a["chapter"])}</span></td>'
        f'<td class="dot">{dots(order, a["sittings"], a["of"])}</td>'
        f'<td class="num">{asked(a)}</td><td class="num"><b>{total(a)}</b></td></tr>'
        for i, a in enumerate(top, 1))
    return f"""
<section class="page">
  <h1>Which topics come up</h1>
  <div class="figure">
    <p class="takeaway">{e(big[0]['name'])} and {e(big[1]['name'])} give the most marks.
    Not every topic comes up in every paper.</p>
    {heatmap(d)}
    <div class="caption">Each number is the marks for that topic in that paper. A dashed box
    means that the topic was not in that paper.{total_note(d)}</div>
  </div>
  <div class="figure">
    <p class="takeaway">Total marks for each topic, all {len(order)} papers</p>
    {hbars([(c['name'], c['marks'], f"about {avg(c):.0f} per paper")
            for c in d['chapters']], d['marks'])}
    <div class="caption">On the right: the average marks for the topic in a paper that had it.</div>
  </div>
</section>
<section class="page">
  <h1>What to learn first</h1>
  <div class="figure">
    <p class="takeaway">The first {PARETO_HEADLINE} actions give {cov[PARETO_HEADLINE]:.0f}% of all the marks.</p>
    {svg_p}
    <div class="caption">All {len(d['actions'])} actions, sorted from most marks to fewest. The
    line shows how much of the paper you cover as you learn more of them.</div>
  </div>
  <div class="figure">
    <p class="takeaway">The {core[1]} Core actions give {100 * core[2] / d['marks']:.0f}% of
    the marks.</p>
    {svg_t}
  </div>
</section>
<section class="page">
  <h1>The {len(top)} actions asked most often</h1>
  <p class="muted">The list uses the number of papers that asked.{order_ex}</p>
  <table class="top">{thead(order, "", "16pt").replace("<th>Action</th>", "<th>Action and topic</th>")}
  <tbody>{trs}</tbody></table>
</section>"""


def subtopic(st, order):
    main = [a for a in st["actions"] if a["tier"] != "rare"]
    once = [a for a in st["actions"] if a["tier"] == "rare"]
    trs = "".join(
        f'<tr><td>{badge(a["tier"])}</td><td><span class="act">{e(a["action"])}</span>'
        + (f'<span class="detail">{e(a["detail"])}</span>' if a.get("detail") else "")
        + f'</td><td class="dot">{dots(order, a["sittings"], a["of"])}</td>'
        f'<td class="num">{asked(a)}</td><td class="num"><b>{total(a)}</b></td></tr>'
        for a in main)
    notes = []
    if st.get("drill"):
        notes.append(f'<div><span class="lab">Practise</span>{e(st["drill"])}</div>')
    if st.get("exact_values"):
        notes.append('<div><span class="lab">Exact values the papers asked for</span><ul>'
                     + "".join(f"<li>{e(x)}</li>" for x in st["exact_values"]) + "</ul></div>")
    if once:
        notes.append(f'<div class="rare"><span class="lab">Rare: asked in {rare_words()[1]}</span><ul>'
                     + "".join(f'<li>{e(a["action"])} <span class="sess">{a["sittings"][0]}</span></li>'
                               for a in once) + "</ul></div>")
    return f"""
<div class="sub">
  <div class="keep">
    <div class="subhead"><h3>{e(st['name'])}</h3>
      <span class="meta">in {len(st['sittings'])} of {len(order)} papers · {st['marks']} marks</span></div>
    {f"<p>{e(st['summary'])}</p>" if st.get('summary') else ""}
  </div>
  {f'<table>{thead(order)}<tbody>{trs}</tbody></table>' if main else ""}
  {f'<div class="notes">{"".join(notes)}</div>' if notes else ""}
</div>"""


def chapter(c, d, i):
    order = d["sittings"]
    ncore = sum(a["tier"] == "core" for s in c["subtopics"] for a in s["actions"])
    return f"""
<section class="page">
  <div class="kicker">Topic {i} of {len(d['chapters'])}</div>
  <div class="chhead"><h1>{e(c['name'])}</h1><div class="stats">
    <div class="stat"><div class="n">{len(c['sittings'])} of {len(order)}</div><div class="l">papers had this topic</div></div>
    <div class="stat"><div class="n">{c['marks'] / len(c['sittings']):.0f}</div><div class="l">marks on average when it comes</div></div>
    <div class="stat"><div class="n">{ncore}</div><div class="l">Core actions</div></div>
  </div></div>
  <p>{e(c.get('summary', ''))}</p>
  <div class="figure">
    <p class="takeaway">Where the marks go in this topic</p>
    {hbars([(s['name'], s['marks'], f"in {len(s['sittings'])} of {len(order)} papers")
            for s in c['subtopics']], c['marks'], label_w=235)}
  </div>
  {"".join(subtopic(s, order) for s in c['subtopics'])}
</section>"""


def checklist(d):
    order = d["sittings"]
    out = []
    for c in d["chapters"]:
        rows = [a for a in sorted(d["actions"], key=rank)
                if a["tier"] == "core" and a["chapter"] == c["name"]]
        if not rows:
            continue
        out.append(f'<tr class="group"><td colspan="5">{e(c["name"])}</td></tr>')
        out += [f'<tr><td><span class="tick"></span></td><td>{e(a["action"])}</td>'
                f'<td class="dot">{dots(order, a["sittings"], a["of"])}</td>'
                f'<td class="num">{asked(a)}</td><td class="num">{total(a)}</td></tr>'
                for a in rows]
    return f"""
<section class="page">
  <h1>Checklist: all Core actions</h1>
  <p class="muted">Tick each action when you can do it without notes.</p>
  <table class="check">{thead(order, "", "18pt")}<tbody>{"".join(out)}</tbody></table>
</section>"""


def page(d):
    kind, level = KIND[d["paper"]]
    body = first(d, kind, level) + overview(d)
    body += "".join(chapter(c, d, i) for i, c in enumerate(d["chapters"], 1))
    body += checklist(d)
    css = CSS.replace("__RUNNING__", f"9626 Paper {d['paper']} · {kind} · action by action")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<title>9626 Paper {d["paper"]} {kind}: action by action</title>'
            f'<style>{css}</style></head><body>{body}</body></html>')


def chrome():
    hits = sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")))
    if not hits:
        sys.exit("no Chromium found; run: npx playwright install chromium")
    return hits[-1]


def build(paper, src=None, out_dir=OUT, keep_html=False):
    d = load(paper, src)
    kind, _ = KIND[paper]
    out = out_dir / f"Paper {paper} - {kind} Deep Dive.pdf"
    doc = page(d)
    if keep_html:
        out.with_suffix(".html").write_text(doc)
    with tempfile.TemporaryDirectory() as tmp:
        src_html = Path(tmp) / "report.html"
        src_html.write_text(doc)
        subprocess.run([chrome(), "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        "--virtual-time-budget=5000", f"--print-to-pdf={out}",
                        src_html.as_uri()], check=True, capture_output=True)
    return out


if __name__ == "__main__":
    keep = "--html" in sys.argv
    for p in [a for a in sys.argv[1:] if a != "--html"] or ["2", "4"]:
        print(build(p, keep_html=keep).name)
