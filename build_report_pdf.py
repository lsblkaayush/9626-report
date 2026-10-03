"""Reports/Paper N - What the past papers show.pdf

One PDF per paper. Everything is a share of the paper, because "a fifth of the
marks" is a thing you can act on and "1,261 marks" is not. Charts are drawn
straight onto the page - no HTML step, no browser, no chart library.

ponytail: hand-rolled bars and lines on a pymupdf canvas. It is about 200 lines
of drawing code, which is less than pulling in a chart stack and fighting its
defaults. If the report ever needs real chart types, swap this file, not the data.
"""
import math
import re
import sys
from pathlib import Path

import pymupdf

from report_stats import PAPER_META, fingerprint, gt_pdf, report_inputs, sitting_of, stats

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Reports"

W, H = 595.0, 842.0
L, R = 56.0, 539.0
CW = R - L

INK = (0.086, 0.098, 0.125)
MUTED = (0.40, 0.43, 0.49)
FAINT = (0.62, 0.65, 0.70)
RULE = (0.87, 0.88, 0.90)
WASH = (0.964, 0.967, 0.973)
ACCENT = (0.043, 0.384, 0.380)
WARN = (0.76, 0.35, 0.10)
GOLD = (0.83, 0.62, 0.15)


def tint(color, amount):
    """Lighten towards white. amount 0 = unchanged, 1 = white."""
    amount = min(max(amount, 0.0), 0.82)
    return tuple(c + (1 - c) * amount for c in color)


def marks_label(n):
    return f"{n} mark" if n == 1 else f"{n} marks"


def clip(text, n):
    """Trim to n chars on a word boundary so a legend never reads 'off-the-sh'."""
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return (cut or text[:n]) + "..."


def fit(text, width, size, font="helv"):
    """Same idea as clip, but measured in points. Stops a cell eating its neighbour."""
    if pymupdf.get_text_length(text, fontname=font, fontsize=size) <= width:
        return text
    words = text.split()
    while words:
        words.pop()
        trial = " ".join(words) + "..."
        if pymupdf.get_text_length(trial, fontname=font, fontsize=size) <= width:
            return trial
    return ""


def wrap(text, width, size, font="helv"):
    out, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if pymupdf.get_text_length(trial, fontname=font, fontsize=size) > width and line:
            out.append(line)
            line = word
        else:
            line = trial
    if line:
        out.append(line)
    return out


class Sheet:
    """A4 pages with a running y cursor and a footer on every page but the cover."""

    def __init__(self, title):
        self.doc = pymupdf.open()
        self.title = title
        self.page = None
        self.y = 0.0
        self.n = 0

    def new(self, top=84.0):
        self.page = self.doc.new_page(width=W, height=H)
        self.n += 1
        self.y = top
        if self.n > 1:
            self.page.insert_text((L, 56), self.title, fontname="helv", fontsize=7.6,
                                  color=FAINT)
            self.page.draw_line((L, 63), (R, 63), color=RULE, width=0.6)
            self.page.insert_text((R - 10, 806), str(self.n - 1), fontname="helv",
                                  fontsize=8, color=FAINT)
        return self.page

    def need(self, height):
        if self.y + height > 794:
            self.new()

    def text(self, s, size=9.8, font="helv", color=INK, lead=None, gap=0.0, width=None):
        lead = lead or size * 1.45
        for line in wrap(s, width or CW, size, font):
            self.need(lead)
            self.page.insert_text((L, self.y), line, fontname=font, fontsize=size, color=color)
            self.y += lead
        self.y += gap

    def h1(self, s):
        self.need(50)
        self.y += 10
        self.page.insert_text((L, self.y), s, fontname="hebo", fontsize=19, color=INK)
        self.y += 9
        self.page.draw_line((L, self.y), (L + 44, self.y), color=ACCENT, width=2.2)
        self.y += 22

    def h2(self, s):
        self.need(30)
        self.y += 12
        self.page.insert_text((L, self.y), s, fontname="hebo", fontsize=11, color=INK)
        self.y += 16

    def kicker(self, s):
        self.page.insert_text((L, self.y), s.upper(), fontname="hebo", fontsize=7.4,
                              color=ACCENT)
        self.y += 15

    def note(self, s):
        self.text(s, size=8.6, color=MUTED, gap=4)


# ----------------------------------------------------------------- charts


def bar_rows(sheet, rows, *, label_w=136, track=196, note_w=None, scale=None,
             fmt="{:.0f}%", color=ACCENT, row_h=None, bar_h=None):
    """One horizontal bar per row: (label, pct, right_note). Longest bar sets the scale.

    row_h is per call. The cover opens it up when a paper has few topics; the inside
    pages stay tight, because they have to fit a whole page of other things.
    """
    top = max(r[1] for r in rows) if scale is None else scale
    top = max(top, 1e-6)
    row_h = row_h or 17
    bar_h = bar_h or (11 if row_h < 20 else 14)
    x_bar = L + label_w
    for i, (label, pct, right) in enumerate(rows):
        sheet.need(row_h + 5)
        y = sheet.y
        mid = y + bar_h / 2 + 3.1
        sheet.page.insert_text((L, mid), fit(label, label_w - 10, 8.8),
                               fontname="helv", fontsize=8.8, color=INK)
        sheet.page.draw_rect(pymupdf.Rect(x_bar, y, x_bar + track, y + bar_h),
                             color=None, fill=WASH, radius=0.3)
        w = track * pct / top
        if w > 0.6:
            sheet.page.draw_rect(pymupdf.Rect(x_bar, y, x_bar + w, y + bar_h),
                                 color=None, fill=tint(color, i * 0.055), radius=0.3)
        sheet.page.insert_text((x_bar + track + 8, mid), fmt.format(pct),
                               fontname="hebo", fontsize=8.8, color=INK)
        if right:
            sheet.page.insert_text((x_bar + track + 44, mid), right,
                                   fontname="helv", fontsize=8.2, color=MUTED)
        sheet.y += row_h
    sheet.y += 7


def stacked(sheet, parts, *, height=16, gap_below=8, keep=5, rest="The rest"):
    """One full-width bar split into labelled segments. parts: (name, pct).

    Anything past the first `keep` segments is merged into one. Slivers you cannot
    label are noise, and every segment that survives gets a legend entry.
    """
    parts = [p for p in parts if p[1] > 0]
    if len(parts) > keep + 1:
        tail = sum(p[1] for p in parts[keep:])
        parts = parts[:keep] + [(rest, tail)]
    sheet.need(height + 34)
    y, x = sheet.y, L
    for i, (_, pct) in enumerate(parts):
        w = CW * pct / 100
        sheet.page.draw_rect(pymupdf.Rect(x, y, x + max(w, 0.4), y + height),
                             color=(1, 1, 1), width=0.7, fill=tint(ACCENT, i * 0.15))
        if w > 24:
            sheet.page.insert_text((x + 5, y + height - 5), f"{pct:.0f}%",
                                   fontname="hebo", fontsize=7.8,
                                   color=(1, 1, 1) if i < 3 else INK)
        x += w
    sheet.y += height + 12
    x = L
    for i, (name, _) in enumerate(parts):
        wdt = pymupdf.get_text_length(name, fontname="helv", fontsize=7.8) + 20
        if x + wdt > R and x > L:
            x = L
            sheet.y += 12
        sheet.page.draw_rect(pymupdf.Rect(x, sheet.y - 5.4, x + 6.4, sheet.y + 1),
                             color=None, fill=tint(ACCENT, i * 0.15), radius=0.3)
        sheet.page.insert_text((x + 11, sheet.y), name, fontname="helv", fontsize=7.8,
                               color=MUTED)
        x += wdt
    sheet.y += 10 + gap_below


def tiles(sheet, items, *, height=74):
    """A row of stat cards: (big, caption)."""
    n = len(items)
    gap = 12
    w = (CW - gap * (n - 1)) / n
    y = sheet.y
    for i, (big, caption) in enumerate(items):
        x = L + i * (w + gap)
        box = pymupdf.Rect(x, y, x + w, y + height)
        sheet.page.draw_rect(box, color=None, fill=WASH, radius=0.06)
        sheet.page.draw_line((x, y), (x, y + height), color=ACCENT, width=2.2)
        sheet.page.insert_text((x + 13, y + 33), big, fontname="hebo", fontsize=23,
                               color=INK)
        yy = y + 50
        for line in wrap(caption, w - 24, 8.2):
            sheet.page.insert_text((x + 13, yy), line, fontname="helv", fontsize=8.2,
                                   color=MUTED)
            yy += 11
    sheet.y = y + height + 16


def callout(sheet, title, body, *, color=ACCENT):
    lines = wrap(body, CW - 34, 9.2)
    h = 26 + 13 * len(lines)
    sheet.need(h + 12)
    box = pymupdf.Rect(L, sheet.y, R, sheet.y + h)
    sheet.page.draw_rect(box, color=None, fill=tint(color, 0.93), radius=0.05)
    sheet.page.draw_line((L, sheet.y), (L, sheet.y + h), color=color, width=2.4)
    sheet.page.insert_text((L + 15, sheet.y + 18), title, fontname="hebo", fontsize=9.2,
                           color=color)
    yy = sheet.y + 33
    for line in lines:
        sheet.page.insert_text((L + 15, yy), line, fontname="helv", fontsize=9.2, color=INK)
        yy += 13
    sheet.y += h + 14


def line_chart(sheet, rows, series, *, height=192, lo=15, hi=94):
    """Grade boundaries over time. rows carry pct dicts; series is [(grade, colour)]."""
    sheet.need(height + 46)
    x0, y0 = L + 26, sheet.y
    plot_w, plot_h = CW - 26 - 18, height  # 18pt gutter so A / C / E sit clear of the line
    y1 = y0 + plot_h

    def py(pct):
        return y1 - (pct - lo) / (hi - lo) * plot_h

    for gl in range(lo, hi + 1, 15):
        yy = py(gl)
        sheet.page.draw_line((x0, yy), (x0 + plot_w, yy), color=RULE, width=0.5)
        sheet.page.insert_text((L, yy + 2.6), f"{gl}%", fontname="helv", fontsize=7,
                               color=FAINT)
    step = plot_w / max(len(rows) - 1, 1)
    for grade, col in series:
        pts = [(x0 + i * step, py(r["pct"][grade])) for i, r in enumerate(rows)]
        for a, b in zip(pts, pts[1:]):
            sheet.page.draw_line(a, b, color=col, width=1.5)
        for p in pts:
            sheet.page.draw_circle(p, 1.7, color=None, fill=col)
        lx, ly = pts[-1]
        sheet.page.insert_text((lx + 8, ly + 2.8), grade, fontname="hebo",
                               fontsize=8.6, color=col)
    sheet.y = y1 + 13
    seen, last_x = set(), -99.0
    for i, r in enumerate(rows):
        if r["year"] in seen:
            continue
        seen.add(r["year"])
        x = x0 + i * step - 8
        if x - last_x < 30:
            continue
        last_x = x
        sheet.page.insert_text((x, sheet.y), str(r["year"]),
                               fontname="helv", fontsize=7, color=FAINT)
    sheet.y += 16


def ladder_chart(sheet, rows, marks, grades, *, label_w=162, track=172):
    """Running share of the paper, one row per topic, with the boundaries marked.

    rows: (label, cumulative_pct, right_note). grades: [(letter, pct_of_paper)].
    The scale is always 0 to 100, because the point of the chart is the distance
    left to the boundary, and a scale that stops at the largest bar hides it.
    """
    x0 = L + label_w
    gx = [(g, x0 + track * pct / 100, pct) for g, pct in grades]
    sheet.need(20)
    for g, x, pct in gx:
        sheet.page.insert_text((x - 6, sheet.y + 2), g, fontname="hebo", fontsize=8,
                               color=WARN)
        sheet.page.insert_text((x - 11, sheet.y + 11), f"{pct:.0f}%", fontname="helv",
                               fontsize=6.6, color=WARN)
    sheet.y += 15
    top = sheet.y
    for i, (label, pct, right) in enumerate(rows):
        y = sheet.y
        mid = y + 9.6
        sheet.page.insert_text((L, mid), fit(label, label_w - 10, 8.8),
                               fontname="helv", fontsize=8.8, color=INK)
        sheet.page.draw_rect(pymupdf.Rect(x0, y, x0 + track, y + 13),
                             color=None, fill=WASH, radius=0.3)
        sheet.page.draw_rect(pymupdf.Rect(x0, y, x0 + track * pct / 100, y + 13),
                             color=None, fill=tint(ACCENT, i * 0.05), radius=0.3)
        sheet.page.insert_text((x0 + track + 8, mid), f"{pct:.0f}%",
                               fontname="hebo", fontsize=8.8, color=INK)
        if right:
            sheet.page.insert_text((x0 + track + 40, mid), right, fontname="helv",
                                   fontsize=7.8, color=MUTED)
        sheet.y += 19
    for _, x, _ in gx:
        sheet.page.draw_line((x, top - 3), (x, sheet.y - 4), color=WARN, width=0.7,
                             dashes="[1 2] 0")
    sheet.y += 10


def dumbbell(sheet, rows, *, label_w=136, track=240):
    """then -> now, one row per topic. rows: (label, then_pct, now_pct)."""
    top = max(max(r[1], r[2]) for r in rows) * 1.12
    x0 = L + label_w
    for label, then, now in rows:
        sheet.need(21)
        y = sheet.y + 7
        sheet.page.insert_text((L, y + 3), label, fontname="helv", fontsize=8.8, color=INK)
        sheet.page.draw_line((x0, y), (x0 + track, y), color=WASH, width=5)
        xa, xb = x0 + track * then / top, x0 + track * now / top
        move = now - then
        col = ACCENT if move >= 5 else WARN if move <= -5 else FAINT
        if abs(move) >= 1:
            sheet.page.draw_line((xa, y), (xb, y), color=tint(col, 0.55), width=3.4)
        sheet.page.draw_circle((xa, y), 3.2, color=(1, 1, 1), width=0.9, fill=FAINT)
        sheet.page.draw_circle((xb, y), 3.6, color=(1, 1, 1), width=0.9, fill=col)
        sheet.page.insert_text((x0 + track + 10, y + 3),
                               f"{then:.0f}% to {now:.0f}% of papers"
                               + ("" if abs(now - then) >= 5 else "   no change"),
                               fontname="helv",
                               fontsize=8.2, color=MUTED)
        sheet.y += 19
    sheet.y += 4


def table(sheet, headers, rows, widths, *, size=8.4):
    sheet.need(20 + 15 * len(rows))
    xs, x = [], L
    for w in widths:
        xs.append(x)
        x += w
    for h, x in zip(headers, xs):
        sheet.page.insert_text((x, sheet.y), h, fontname="hebo", fontsize=7.4, color=MUTED)
    sheet.y += 6
    sheet.page.draw_line((L, sheet.y), (R, sheet.y), color=RULE, width=0.6)
    sheet.y += 12
    for r in rows:
        for cell, x, w in zip(r, xs, widths):
            sheet.page.insert_text((x, sheet.y), fit(str(cell), w - 10, size),
                                   fontname="helv", fontsize=size, color=INK)
        sheet.y += 15
    sheet.y += 4


# ----------------------------------------------------------------- copy

# Report choices. Each one drives both the rows it selects and the sentence that describes
# them, so the two cannot drift apart (IT-P5-LINT: the acceptance test changes each one and
# the printed words follow).
TOP_N = 3          # "the top N topics"
NEXT_N = 3         # Paper 4: "each of the next N topics"
NEXT_SKILLS = 4    # Paper 4: "the next N skills"
MOSTLY_PCT = 50    # a topic has "most of its marks in a single section" above this share of it
USUAL_PCT = 50     # a usual topic is in at least this share of all papers
FIRM_PCT = 50      # a task position "carries the same topic" in at least this share of its sittings
EXTRA_TOPICS = 2   # the safety margin the payoff page adds to the boundary line


def T(s, tid):
    """One topic's row from the headline slice."""
    return next(t for t in s["topics"] if t["id"] == tid)


def SH(s, tid):
    """One topic's paper shares before and since the syllabus change, and how many papers
    before the change had it (then_n, an exact count)."""
    row = next((x for x in s["shift"] if x["id"] == tid),
               {"id": tid, "then": 0.0, "now": 0.0})
    return {**row, "then_n": s["then_count"].get(tid, 0)}


def SUB(s, sid, key="pct"):
    return next(x[key] for x in s["subtopics"] if x["id"] == sid)


def syl(s):
    """The year of the syllabus change (report_stats.CURRENT_SYLLABUS_FROM)."""
    return s["syllabus_from"]


def since_count(s, tid):
    """How many papers since the syllabus change had the topic, from the share and the paper count."""
    return round(SH(s, tid)["now"] * s["papers_since_2022"] / 100)


def top3(s):
    return sum(t["marks_pct"] for t in s["topics"][:TOP_N])


def named_top(s, *rows):
    """The top TOP_N topics, checked against the topics the copy names in words (Paper 2:
    spreadsheets, databases and video). The build stops when they are no longer the top ones."""
    top = s["topics"][:TOP_N]
    assert {t["id"] for t in top} == {r["id"] for r in rows}, (
        f"Paper {s['paper']}: the top {TOP_N} topics are not the ones the copy names")
    return top


def y26_name(s):
    """'March 2026': the sitting of the newest paper, from its code."""
    return sitting_of(s["y2026"]["code"])[2]


def y26_marks(s, tid):
    """Marks that topic carried in the newest paper, split the same way as the shares."""
    got = 0.0
    for q in s["y2026"]["questions"]:
        tops = {t.split(".")[0] for t in q["tags"]}
        if tid in tops:
            got += q["marks"] / len(tops)
    return got, sum(q["marks"] for q in s["y2026"]["questions"])


# Counts printed as words. The table maps the word to its value; the printed word is
# looked up from a computed count, never typed into the copy.
_WORD_VALUE = {"no": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
               "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
               "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
               "nineteen": 19, "twenty": 20}
COUNT_WORD = {v: k for k, v in _WORD_VALUE.items()}


def count_word(n):
    return COUNT_WORD.get(n, str(n))


def cap(text):
    return text[:1].upper() + text[1:]


def n_of(k, noun):
    """'no papers', 'one paper', 'three papers': a computed count in words, with its noun."""
    return f"{count_word(k)} {noun if k == 1 else noun + 's'}"


def span_words(lo, hi):
    """A min..max count in words: 'X' when equal, 'X or Y' one apart, 'X to Y' further apart."""
    if lo == hi:
        return count_word(lo)
    return f"{count_word(lo)} {'or' if hi - lo == 1 else 'to'} {count_word(hi)}"


def years_phrase(ys):
    """[2017, 2018] -> '2017 and 2018'; a run of three or more -> '2017 to 2019'."""
    ys = sorted(ys)
    if len(ys) == 1:
        return str(ys[0])
    if len(ys) > 2 and ys == list(range(ys[0], ys[-1] + 1)):
        return f"{ys[0]} to {ys[-1]}"
    return ", ".join(map(str, ys[:-1])) + " and " + str(ys[-1])


def q_span(s):
    """Questions in one paper, fewest to most, over the headline papers (D19)."""
    return span_words(s["q_per_paper"]["min"], s["q_per_paper"]["max"])


def t_span(s):
    """Tasks in one paper, fewest to most, over the headline papers (D29)."""
    return span_words(s["tasks_per_paper"]["min"], s["tasks_per_paper"]["max"])


def last_task(s):
    """The highest task number (D29). The average marks for it come from analysis_*.json,
    so the two sources must agree on which task is the last one."""
    n = s["tasks_per_paper"]["last"]
    assert n == max(s["qnum_avg_marks"]), (
        f"last task {n} from the bank != last task {max(s['qnum_avg_marks'])} in analysis")
    return n


def paper_minutes(s):
    """The length of the paper in minutes, from PAPER_META ("1h 45m")."""
    h, m = (int(x) for x in s["length"].replace("h", "").replace("m", "").split())
    return h * 60 + m


def per_mark(s):
    """Minutes the paper gives each mark: its length over the newest maximum."""
    return paper_minutes(s) / s["max_now"]


def secs(s):
    """Seconds for each mark, as printed."""
    return f"{per_mark(s) * 60:.0f}"


def common_pair(s):
    """The two most common question sizes, smaller first, and the share of questions they cover."""
    a, b = sorted(x["marks"] for x in s["sizes"][:2])
    return a, b, sum(x["pct"] for x in s["sizes"][:2])


def under_pct(s, marks):
    """Share of the questions worth less than `marks`."""
    return sum(x["pct"] for x in s["sizes"] if x["marks"] < marks)


def a_peak(s):
    """The highest A boundary (rounded) that every session of a year printed, those years, and
    the year where the falling run of yearly averages that starts with the last of them ends."""
    by = {}
    for r in s["thresholds"]:
        by.setdefault(r["year"], []).append(r["pct"]["A"])
    top = max(round(v) for vs in by.values() for v in vs)
    years = [y for y, vs in sorted(by.items()) if all(round(v) == top for v in vs)]
    avg = {y: sum(vs) / len(vs) for y, vs in by.items()}
    end = years[-1]
    for y in sorted(y for y in avg if y > years[-1]):
        if avg[y] >= avg[end]:
            break
        end = y
    assert years[-1] < syl(s) and end > years[-1], f"Paper {s['paper']}: no falling run after {years}"
    return {"pct": top, "years": years_phrase(years), "fell_to": end}


def old_max(s):
    """The maximum mark of the papers before the syllabus change."""
    got = {r["max"] for r in s["thresholds"] if r["year"] < syl(s)}
    assert len(got) == 1, f"Paper {s['paper']}: several old maxima {got}"
    return got.pop()


def size_band(s):
    """'N% of the tasks are worth X to Y marks' (report_stats.WIDE_BAND)."""
    b = s["size_band"]
    return f"{b['share']:.0f}% of the tasks are worth {b['lo']:.0f} to {b['hi']:.0f} marks"


def usually(s, row):
    """'usually worth X to Y marks' for a topic row: the middle half of the papers that have the
    topic (report_stats.USUAL_BAND), said only when more than half of them fall inside it."""
    b = s["topic_band"][row["id"]]
    assert b["share"] > 50, f"Paper {s['paper']}: topic {row['id']} band holds only {b['share']:.0f}% of its papers"
    return f"usually worth {b['lo']:.0f} to {b['hi']:.0f} marks"


def new(row):
    """A topic the copy calls new (an SH row) must be in no paper before the syllabus change."""
    assert row["then_n"] == 0, f"topic {row['id']} is not new: {row['then_n']} papers had it before"
    return row


def long_words(s):
    """The two command words with the most parts at the largest part size, and the
    counts that back the "do these last" advice (D33). Nothing here is typed: a rank
    claim such as "it has the most marks" was wrong once (Evaluate parts average more
    than Discuss parts), so the advice prints the counts instead."""
    cs = s["command_sizes"]
    a, b = cs["words"][:2]
    # same parts as the command-word bars: their marks must add up to the same total
    assert abs(sum(x["parts"] * x["mean"] for x in cs["words"]) - s["cmd_total"]) < 1e-6, (
        "command_sizes and commands disagree on the marks they cover")
    assert a["at_top"] >= b["at_top"] >= max([x["at_top"] for x in cs["words"][2:]] or [0])
    # "No part is worth more than top marks" covers the parts without text too
    assert cs["top"] == cs["largest_part"], (
        f"largest part with a command word {cs['top']} != largest part {cs['largest_part']}")
    return {"a": a["word"], "b": b["word"], "k": a["at_top"] + b["at_top"],
            "n": cs["at_top"], "top": cs["top"], "y0": cs["years"][0], "y1": cs["years"][1]}


def skill(s, name):
    return next(x for x in s["skills"]["skills"] if x["name"] == name)


def every_or(s, tid, what="paper"):
    """'in every paper since <change>' when that is true, else the share."""
    now = SH(s, tid)["now"]
    return (f"in every {what} since {syl(s)}" if now >= 99.95
            else f"in {now:.0f}% of papers since {syl(s)}")


def names_of(topics):
    n = [t["name"][0].lower() + t["name"][1:] if t["name"] != "IT in society" else t["name"]
         for t in topics]
    # Oxford comma: the names have "and" inside them ("hardware and software")
    return ", ".join(n[:-1]) + ", and " + n[-1]


def p3_top_note(s):
    """Paper 3: how often the top topics and the others appear (headline slice)."""
    top, rest = s["topics"][:TOP_N], s["topics"][TOP_N:]
    low = min(t["appears_pct"] for t in top)
    head = (f"The top {count_word(TOP_N)} topics are in every paper since {s['headline_from']}."
            if low >= 99.95 else
            f"The top {count_word(TOP_N)} topics are each in {low:.0f}% of papers or more.")
    return (head + f" Each of the other topics is in {max(t['appears_pct'] for t in rest):.0f}% "
            "of papers or fewer.")


COPY = {
 "1": {
  "tiles": lambda s: [
      (f"{s['grade_pct']['A']:.0f}%", "is enough for an A in recent sittings"),
      (f"{next(c['pct'] for c in s['commands'] if c['word'] == 'Describe'):.0f}%",
       "of the marks are for Describe questions"),
      (f"{SH(s, '4')['then']:.0f} to {SH(s, '4')['now']:.0f}%",
       f"of papers have an algorithms question. Before {syl(s)}, "
       f"{n_of(SH(s, '4')['then_n'], 'paper')} had one.")],
  "short": [
      lambda s: (f"The syllabus changed in {syl(s)}. All the numbers below use only the "
                 "sittings after that change."
                 if s["headline_from"] == syl(s) else None),
      lambda s: (f"{cap(count_word(TOP_N))} topics give {top3(s):.0f}% of the marks: "
                 f"{names_of(s['topics'][:TOP_N])}."),
      lambda s: (f"Algorithms and flowcharts are new. They are now in "
                 f"{new(SH(s, '4'))['now']:.0f}% of papers."),
      lambda s: (f"Before {syl(s)}, spreadsheets were in {SH(s, '8')['then']:.0f}% of papers and "
                 f"networks in {SH(s, '14')['then']:.0f}%. Now spreadsheets are in "
                 f"{SH(s, '8')['now']:.0f}%, and networks in {SH(s, '14')['now']:.0f}%."),
      lambda s: (f"An A needs about {s['grade_pct']['A']:.0f}% of the marks. A C needs about "
                 f"{s['grade_pct']['C']:.0f}%.")],
  "topic_note": "The bar shows the share of the marks. The text shows how many papers contain the topic. A small topic can still be in almost every paper.",
  "threshold_note": lambda s: (
      f"The A boundary went down to {min(r['pct']['A'] for r in s['thresholds']):.0f}% "
      f"and is now {s['thresholds'][-1]['pct']['A']:.0f}%. Cambridge sets the boundary after it "
      "marks the papers. Use the recent numbers. Do not use the old ones."),
  "shape_note": lambda s: (
      f"{sum(x['pct'] for x in s['sizes'][:3]):.0f}% of the questions are worth "
      f"{s['sizes'][0]['marks']}, {s['sizes'][1]['marks']} or {s['sizes'][2]['marks']} marks. "
      f"At {secs(s)} seconds for each mark, they are "
      f"{s['sizes'][0]['marks'] * per_mark(s):g} minutes, {s['sizes'][1]['marks'] * per_mark(s):g} "
      f"minutes and {s['sizes'][2]['marks'] * per_mark(s):g} minutes of work."),
  "inside": "the topics  ·  the boundaries  ·  the shape  ·  what has changed  ·  how far "
            "revision gets you  ·  what to do",
  "advice": [
      ("Learn algorithms and flowcharts", lambda s: (
          f"This is the largest change to the paper. Before {syl(s)}, "
          f"{n_of(SH(s, '4')['then_n'], 'paper')} had a question on it. "
          f"Now it is in {SH(s, '4')['now']:.0f}% of papers, and it is {usually(s, T(s, '4'))}. "
          "You must read pseudocode, find the errors in it, and complete flowcharts. The topic "
          "is small and you can learn all of it."
          if s["shift"][0]["id"] == "4" else None)),
      ("Learn data processing first", lambda s: (
          f"It gives {T(s, '1')['marks_pct']:.0f}% of the marks and it is {every_or(s, '1')}. "
          "Learn the difference between data and information. Learn encryption, validation "
          "and verification, and batch and real-time processing.")),
      ("Do not ignore monitoring and control", lambda s: (
          f"It is now in {SH(s, '3')['now']:.0f}% of papers. Before {syl(s)} it was in "
          f"{SH(s, '3')['then']:.0f}%. Learn the sensors and what each sensor measures. Learn "
          "calibration and feedback loops. Know the difference between a monitoring system "
          "and a control system.")),
      ("Write full sentences, not bullet points", lambda s: (
          f"The examiner reports for {s['er_bullets']['hit']} of the {s['er_bullets']['of']} "
          f"sittings since {s['er_bullets']['since']} say this. A detailed answer is needed, and "
          "bullet points cannot give one. Write each point as a sentence. Then explain it, or "
          "connect it to the scenario in the question. A point that does not fit the scenario "
          "gets no marks.")),
      ("Answer the command word", "Describe needs facts. Explain needs a reason for each fact. Evaluate needs both sides and then a decision. Discuss needs more than one view."),
      (lambda s: f"Use {secs(s)} seconds for each mark", lambda s: (
          f"A {s['sizes'][0]['marks']}-mark question is a "
          f"{s['sizes'][0]['marks'] * per_mark(s):g}-minute question. If you write for longer, "
          "you do not have the time you need at the end of the paper.")),
      ("Ignore the removed topics in old papers", "Old papers ask about RAM and ROM, printers, ISDN, and health and safety. The current syllabus does not include them. Old papers also ask about LAN and WAN. These are still in the syllabus, but only for Paper 3. Spreadsheets are still in this paper. Use old papers for practice, but do not plan your revision from them.")],
 },
 "2": {
  "tiles": lambda s: [
      (f"{s['grade_pct']['A']:.0f}%", "of the marks gives you an A in recent sittings"),
      (f"{sum(t['marks_pct'] for t in named_top(s, T(s, '8'), T(s, '10'), T(s, '11'))):.0f}%",
       "of the marks are spreadsheets, databases and video"),
      (f"{T(s, '11')['appears_pct']:.0f}%",
       "of papers contain a video task, more than any other topic")],
  "short": [
      lambda s: ("Spreadsheets, databases and video give "
                 f"{sum(t['marks_pct'] for t in named_top(s, T(s, '8'), T(s, '10'), T(s, '11'))):.0f}% "
                 "of the marks. The split is "
                 + " / ".join(f"{t['marks_pct']:.0f}" for t in s["topics"][:TOP_N]) + "."),
      lambda s: (f"Video is in {T(s, '11')['appears_pct']:.0f}% of papers. Databases are in "
                 f"{T(s, '10')['appears_pct']:.0f}%, but they come as one large task."),
      lambda s: (f"Task 1 gives {s['qnum_avg_marks'][1]:.0f} marks on average. Task 10 gives "
                 f"about {s['qnum_avg_marks'][10]:.0f}. The marks are at the start."),
      lambda s: (f"An A needs about {s['grade_pct']['A']:.0f}% of the marks. That is more than "
                 "both theory papers."),
      "The filename is part of the mark. A correct file with the wrong name gets zero."],
  "topic_note": lambda s: (
      "The bar shows the share of the marks. The text shows how many papers contain the topic. "
      f"The {count_word(TOP_N)} largest topics each give between "
      f"{min(t['marks_pct'] for t in s['topics'][:TOP_N]):.0f}% and "
      f"{max(t['marks_pct'] for t in s['topics'][:TOP_N]):.0f}% of the marks."),
  "threshold_note": lambda s: (
      "This paper needs a higher percentage than both theory papers. An A needs about "
      f"{s['grade_pct']['A']:.0f}% and a C needs about {s['grade_pct']['C']:.0f}%. For an A you "
      f"can drop only about {s['max_now'] - s['grade_raw']['A']:.0f} marks in the whole paper."),
  "shape_note": lambda s: (
      "Task numbers do not show difficulty. Some sittings use "
      f"{count_word(s['tasks_per_paper']['min'])} large tasks. Other sittings divide the same "
      f"work into {count_word(s['tasks_per_paper']['max'])} steps. Read the marks before you start."),
  "skills_note": lambda s: (
      f"Every sitting of this paper from {s['skills_years'][0]} to {s['skills_years'][1]}, read "
      "for the operations it asks for. "
      f"The bar is how many of the {s['skills']['sittings']} sittings need that skill. This is "
      "not the same as the mark share: exporting a file is a small part of a task, but you "
      f"meet it in {skill(s, 'Exporting to the named file')['papers']} of the "
      f"{s['skills']['sittings']} sittings."),
  "inside": "the topics  ·  the boundaries  ·  the shape  ·  what changed  ·  how far "
            "revision gets you  ·  the skills  ·  what to do",
  "advice": [
      (lambda s: f"Learn all {count_word(len(named_top(s, T(s, '8'), T(s, '10'), T(s, '11'))))} topics",
       lambda s: (
          f"Spreadsheets give {T(s, '8')['marks_pct']:.0f}% of the marks, databases give "
          f"{T(s, '10')['marks_pct']:.0f}% and video gives {T(s, '11')['marks_pct']:.0f}%. "
          "There is no part of this paper that you can leave out.")),
      ("Practise the operations, do not read about them", lambda s: (
          "The same operations come back in most sittings. Exporting to the named file is in "
          f"{skill(s, 'Exporting to the named file')['papers']} of the "
          f"{s['skills']['sittings']} sittings. Trimming and cropping video is in "
          f"{skill(s, 'Trimming and cropping video')['papers']}. Practise each one until you "
          "can do it without the menu.")),
      ("Learn the formulae and functions", lambda s: (
          f"One syllabus section, {SUB(s, '8.1', 'id')} {SUB(s, '8.1', 'name')}, gives "
          f"{SUB(s, '8.1'):.0f}% of the paper. Learn absolute and relative references, IF and "
          "nested IF, VLOOKUP and HLOOKUP, and COUNTIF and SUMIF.")),
      ("Learn the database task as one procedure", "Open the CSV file. Find the entities. Normalise the data to 3NF. Set the data types and the validation. Make the relationships. Write the query. Format the report. Export it to PDF on one page. Do this procedure again until you know the order."),
      ("Learn how to export video", "Export and file format give more marks than the editing itself. Check the aspect ratio, the frame size, the file format and the filename."),
      ("Divide your time by marks", lambda s: (
          f"In {s['biggest_task']['sitting']}, the largest task was worth "
          f"{s['biggest_task']['marks']:.0f} marks and the other tasks "
          f"{s['biggest_task']['lo']:.0f} to {s['biggest_task']['hi']:.0f} marks each. That task "
          f"needed about {s['biggest_task']['marks'] * per_mark(s):.0f} of the "
          f"{paper_minutes(s)} minutes. Do not give the same time to each task.")),
      ("Keep time for the written parts", "The Analyse and Evaluate parts come after the build. At that point you may have no time left.")],
 },
 "3": {
  "tiles": lambda s: [
      (f"{s['grade_pct']['A']:.0f}%", "of the marks gives you an A in recent sittings"),
      (f"{top3(s):.0f}%", f"of the marks are in {count_word(TOP_N)} topics"),
      (f"{common_pair(s)[2]:.0f}%",
       f"of the questions are worth {common_pair(s)[0]} or {common_pair(s)[1]} marks")],
  "short": [
      lambda s: (f"The syllabus changed in {syl(s)}. All the numbers below use only the "
                 "sittings after that change."
                 if s["headline_from"] == syl(s) else None),
      lambda s: (f"{names_of(s['topics'][:TOP_N])[0].upper()}{names_of(s['topics'][:TOP_N])[1:]} give "
                 f"{top3(s):.0f}% of the marks."),
      lambda s: (f"All {count_word(TOP_N)} of those topics are in every paper since {s['headline_from']}."
                 if all(t["appears_pct"] >= 99.95 for t in s["topics"][:TOP_N]) else
                 f"Those {count_word(TOP_N)} topics are in " + ", ".join(
                     f"{t['appears_pct']:.0f}%" for t in s["topics"][:TOP_N]) + " of papers."),
      lambda s: (f"Most questions are worth {common_pair(s)[0]} or {common_pair(s)[1]} marks. "
                 f"Only {under_pct(s, common_pair(s)[0]):.0f}% are worth less than "
                 f"{common_pair(s)[0]} marks."
                 if common_pair(s)[2] > 50 else None),
      lambda s: (f"An A needs about {s['grade_pct']['A']:.0f}% of the marks. In "
                 f"{a_peak(s)['years']} it needed {a_peak(s)['pct']}%.")],
  "topic_note": lambda s: (
      "The bar shows the share of the marks. The text shows how many papers contain the topic. "
      + p3_top_note(s)),
  "threshold_note": lambda s: (
      f"This paper needed {a_peak(s)['pct']}% for an A in {a_peak(s)['years']}. "
      f"The boundary fell each year to {a_peak(s)['fell_to']}, and it now needs about "
      f"{s['grade_pct']['A']:.0f}%. Plan from the recent numbers, not the old ones."),
  "shape_note": lambda s: (
      f"{common_pair(s)[2]:.0f}% of the questions are worth {common_pair(s)[0]} or "
      f"{common_pair(s)[1]} marks, and the paper has {q_span(s)} questions. At {secs(s)} "
      f"seconds for each mark, each question is {common_pair(s)[0] * per_mark(s):g} to "
      f"{common_pair(s)[1] * per_mark(s):g} minutes of work."),
  "inside": "the topics  ·  the boundaries  ·  the shape  ·  what has changed  ·  how far "
            "revision gets you  ·  what to do",
  "advice": [
      ("Learn communications technology first", lambda s: (
          f"It gives {T(s, '14')['marks_pct']:.0f}% of the marks and it is {every_or(s, '14')}. "
          "Learn network protocols, wireless technology, network servers, data transmission "
          "and network security.")),
      ("Do not ignore IT in society", lambda s: (
          f"It gives {T(s, '12')['marks_pct']:.0f}% of the marks and it is {every_or(s, '12')}. "
          "Learn digital currencies, data mining, social networking services, the impact of "
          "IT, and technology enhanced learning. There are no calculations in this content.")),
      ("Learn the system life cycle in order", "The stages are analysis, design, development and testing, implementation, documentation, evaluation, and maintenance. Questions usually name one stage and ask what happens in it."),
      ("Apply each point to the scenario", "The examiner reports say that short, bulleted lists do not get full marks at A Level. Write each point as a full sentence. Then connect it to the scenario in the question."),
      ("Practise the diagrams", "Some questions ask you to complete a data flow diagram or a system flowchart. Learn the symbols. You cannot get those marks with words."),
      (lambda s: f"Do the {long_words(s)['a']} and {long_words(s)['b']} questions last",
       lambda s: (
          f"No part is worth more than {long_words(s)['top']} marks. From "
          f"{long_words(s)['y0']} to {long_words(s)['y1']}, {long_words(s)['k']} of the "
          f"{long_words(s)['n']} parts worth {long_words(s)['top']} marks were "
          f"{long_words(s)['a']} or {long_words(s)['b']} questions. They need the most "
          "time. Get the certain marks first.")),
      (lambda s: f"Do not plan from papers before {syl(s)}", lambda s: (
          f"Those papers are worth {old_max(s)} marks. They contain AS content that this paper "
          f"no longer uses. In {a_peak(s)['years']} an A needed {a_peak(s)['pct']}%, against "
          f"about {s['grade_pct']['A']:.0f}% now. Use them for extra practice only."))],
 },
 "4": {
  "tiles": lambda s: [
      (f"{s['grade_pct']['A']:.0f}%", "is enough for an A. No other 9626 paper needs so much."),
      (f"{T(s, '19')['marks_pct'] + T(s, '20')['marks_pct']:.0f}%",
       "of the marks are graphics and animation"),
      (f"{SH(s, '17')['then']:.0f} to {SH(s, '17')['now']:.0f}%",
       f"of papers have a data visualisation task. Before {syl(s)}, "
       f"{n_of(SH(s, '17')['then_n'], 'paper')} had one.")],
  "short": [
      lambda s: ("This paper has the highest boundary in the qualification. An A needs about "
                 f"{s['grade_pct']['A']:.0f}% of the marks."),
      lambda s: (f"Graphics and animation give "
                 f"{T(s, '19')['marks_pct'] + T(s, '20')['marks_pct']:.0f}% of the marks. "
                 f"Graphics is in {T(s, '19')['appears_pct']:.0f}% of papers and animation in "
                 f"{T(s, '20')['appears_pct']:.0f}%."),
      lambda s: ("Data analysis and visualisation is new. It is in "
                 f"{new(SH(s, '17'))['now']:.0f}% of papers since {syl(s)} and "
                 f"it gave {y26_marks(s, '17')[0]:.0f} of the {y26_marks(s, '17')[1]} marks in "
                 f"{y26_name(s)}."),
      lambda s: (f"Mail merge is in fewer papers now. Before {syl(s)} it was in "
                 f"{SH(s, '18')['then']:.0f}% of papers. Since {syl(s)} it is in "
                 f"{SH(s, '18')['now']:.0f}%, {since_count(s, '18')} papers out of "
                 f"{s['papers_since_2022']}."
                 if SH(s, '18')['then'] > SH(s, '18')['now'] else None),
      lambda s: (f"The tasks are large. {size_band(s)}, so one lost "
                 f"{s['size_band']['hi']:.0f}-mark task is "
                 f"{s['size_band']['hi'] / s['max_now'] * 100:.0f}% of the paper.")],
  "topic_note": lambda s: (
      "The bar shows the share of the marks. The text shows how many papers contain the "
      f"topic. The small topics are the risk, because each of the next {count_word(NEXT_N)} is "
      f"still in {min(t['appears_pct'] for t in s['topics'][TOP_N:TOP_N + NEXT_N]):.0f}% of "
      "papers or more."),
  "threshold_note": lambda s: (
      f"An A needs {s['grade_pct']['A']:.0f}% of the marks and a C needs "
      f"{s['grade_pct']['C']:.0f}%. No other component in 9626 needs so much. For an A you can "
      f"drop only about {s['max_now'] - s['grade_raw']['A']:.0f} marks in the whole paper."),
  "shape_note": lambda s: (
      f"The paper has {t_span(s)} tasks and {size_band(s)}. Task 1 gives "
      f"{s['qnum_avg_marks'][1]:.0f} marks on average. Task {last_task(s)}, when the paper has "
      f"one, gives {s['qnum_avg_marks'][last_task(s)]:.0f}."),
  "skills_note": lambda s: (
      f"Every sitting of this paper from {s['skills_years'][0]} to {s['skills_years'][1]}, read "
      "for the operations it asks for. "
      f"The bar is how many of the {s['skills']['sittings']} sittings need that skill. "
      f"Animation is in {skill(s, 'Animation')['papers']} of them. The next "
      f"{count_word(NEXT_SKILLS)} skills are each in at least "
      f"{min(x['papers'] for x in s['skills']['skills'][1:1 + NEXT_SKILLS])} of them."),
  "inside": "the topics  ·  the boundaries  ·  the shape  ·  what changed  ·  how far "
            "revision gets you  ·  the skills  ·  what to do",
  "advice": [
      ("Learn vector graphics first", lambda s: (
          f"It gives {SUB(s, '19.2'):.0f}% of the paper. Draw shapes at an exact size. Convert "
          "shapes and text to curves. Use gradients and outlines. Trace a supplied image and "
          "remove all the bitmap parts.")),
      ("Animation is almost certain", lambda s: (
          f"It is in {T(s, '20')['appears_pct']:.0f}% of papers and it gives "
          f"{T(s, '20')['marks_pct']:.0f}% of the marks. Learn keyframes, tweening, frame rate, "
          "layers and masks. Learn how to export a gif that loops at a given frame size.")),
      ("Start data visualisation now", lambda s: (
          f"Before {syl(s)}, {n_of(SH(s, '17')['then_n'], 'paper')} had this content. It gave "
          f"{y26_marks(s, '17')[0]:.0f} of the {y26_marks(s, '17')[1]} marks in {y26_name(s)}. "
          "Learn charts with equal axis ranges, dashboard sheets, charts that a selector "
          "controls, and rolling averages.")),
      ("Keep your spreadsheet skills", lambda s: (
          f"Spreadsheets give {T(s, '8')['marks_pct']:.0f}% of the marks and they are in "
          f"{T(s, '8')['appears_pct']:.0f}% of papers. This is AS content that you already know. "
          "The data visualisation tasks also use it.")),
      ("Read code, do not write new code", "Web questions usually ask you to comment code or to correct it. Practise with JavaScript that another person wrote. Say what each line does."),
      ("Never leave a task", lambda s: (
          f"An incomplete {s['sizes'][0]['marks']}-mark task still gets marks. An empty task gets "
          "none. Save a simple version with the correct filename, then continue.")),
      ("Put your details in every file", "The paper tells you to put your name, centre number and candidate number in each file. Those marks are easy to get.")],
 },
}


def txt(v, s):
    """COPY values are text or a function of the stats. A function returns None when the
    data no longer supports its sentence; the build then refuses rather than print it."""
    out = v(s) if callable(v) else v
    assert out is not None, f"Paper {s['paper']}: a copy line's claim no longer holds on the data"
    return out


CHEAT = [
    ("Describe", "Give the features or the main points.", "one point for each mark"),
    ("Explain", "Give a reason for each point.", "point, then because"),
    ("Evaluate", "Give the value or the importance of it.", "both sides, then a decision"),
    ("Discuss", "Write about the topic in detail.", "plan it before you write"),
    ("Analyse", "Show how the parts connect.", "structure, not opinion"),
    ("Justify", "Give the evidence for the case.", "reasons, not repetition"),
    ("Compare", "Give the similarities and the differences.", "one point against another"),
    ("Contrast", "Give the differences only.", "no similarities"),
    ("Define", "Give the exact meaning.", "one sentence"),
    ("Identify / State", "Name it, or write it in clear words.", "a few words"),
]

LEAKS = [
    ("The wrong filename", "The file is correct but the name is not. The task then gets no "
                           "marks. You lose all of them for one small error."),
    ("The wrong file format", "A .docx file when the task asks for .pdf. Or a video in the "
                              "wrong container. The front page of the paper gives a warning."),
    ("An empty task", "An incomplete large task still gets marks. An empty task gets none."),
    ("No candidate details", "Put your name, centre number and candidate number in each file "
                             "that asks for them."),
    ("No time for the written parts", "The written parts are at the end of the paper. Leave "
                                      "time for them."),
]


# ----------------------------------------------------------------- pages


# A topic below this share of the marks gets no bar on the cover (D08).
SMALL_PCT = 1


def small_topics(s):
    """Topics too small for a cover bar (0 < share < SMALL_PCT). The cover counts them and
    promises they are on the next page; page_topics names them there."""
    return [t for t in s["topics"] if 0 < t["marks_pct"] < SMALL_PCT]


def cover(sheet, s, c):
    p = sheet.new(top=150)
    p.draw_rect(pymupdf.Rect(0, 0, W, 8), color=None, fill=ACCENT)
    p.insert_text((L, 112), "CAIE 9626 · INFORMATION TECHNOLOGY", fontname="hebo",
                  fontsize=8, color=ACCENT)
    p.insert_text((L, 158), f"Paper {s['paper']}", fontname="hebo", fontsize=42, color=INK)
    p.insert_text((L, 186), f"{s['kind']}   ·   {s['length']}   ·   {s['max_now']} marks   ·   {s['level']}",
                  fontname="helv", fontsize=12, color=MUTED)
    sheet.y = 214
    p.draw_line((L, sheet.y), (R, sheet.y), color=RULE, width=0.8)
    sheet.y += 26
    tiles(sheet, c["tiles"](s), height=76)
    sheet.y += 2
    sheet.kicker("the short version")
    for i, line in enumerate(c["short"], 1):
        line = txt(line, s)
        sheet.page.insert_text((L, sheet.y + 1), f"{i}", fontname="hebo", fontsize=10,
                               color=ACCENT)
        for ln in wrap(line, CW - 22, 10.4):
            sheet.page.insert_text((L + 20, sheet.y), ln, fontname="helv", fontsize=10.4,
                                   color=INK)
            sheet.y += 14.2
        sheet.y += 5
    sheet.y += 6
    shown = [t for t in s["topics"] if t["marks_pct"] >= SMALL_PCT][:11]
    # Papers 2 and 4 have a quarter of the topics Paper 1 has. Without this the cover
    # ends halfway down the page and reads as a rendering fault.
    row_h = 17 if len(shown) > 6 else 26
    block = 15 + row_h * len(shown) + 7 + 38
    sheet.y += max(0.0, min(110.0, (706 - block - sheet.y) / 2))
    sheet.kicker("what the paper is made of, "
                 + (f"{s['headline_from']} onwards" if s["headline_from"] > s["first_year"]
                    else f"{s['first_year']} to {s['last_year']}"))
    bar_rows(sheet, [(t["name"], t["marks_pct"], f"in {t['appears_pct']:.0f}% of papers")
                     for t in shown], row_h=row_h, label_w=158, track=174)
    # Counted from the same list page_topics names, so "next page" stays true (D08).
    tail = len(small_topics(s))
    extra = ("" if not tail else f" One other topic gives less than {SMALL_PCT}%. It is named "
             "on the next page." if tail == 1 else f" {tail} other topics give less than "
             f"{SMALL_PCT}% each. They are named on the next page.")
    if s["headline_from"] == s["first_year"]:
        extra += (" Percentages cover the whole run. Where the text above gives a figure for "
                  f"{syl(s)} onwards, it will not match the bar.")
    sheet.note(txt(c["topic_note"], s) + extra)

    # One line, not a five-row table: on a cover this dense it either fits on every
    # paper or it has to go, and a block that appears on one report and not the next
    # reads as a bug.
    sheet.y = 736
    p.insert_text((L, sheet.y), "INSIDE", fontname="hebo", fontsize=7.4, color=ACCENT)
    p.insert_text((L + 46, sheet.y), fit(c["inside"], CW - 46, 8.4),
                  fontname="helv", fontsize=8.4, color=MUTED)

    sheet.y = 754
    p.draw_line((L, sheet.y), (R, sheet.y), color=RULE, width=0.6)
    sheet.y += 14
    p.insert_text((L, sheet.y), f"Every {s['kind'].lower()} paper from {s['first_year']} to {s['last_sitting']}: {s['papers']} papers and "
                                f"{s['questions']} question parts, each tagged to a syllabus section.",
                  fontname="helv", fontsize=8, color=MUTED)
    p.insert_text((L, sheet.y + 12), "The grade boundaries are the published Cambridge figures. "
                                     "All the values are a share of the paper.",
                  fontname="helv", fontsize=8, color=MUTED)


def page_topics(sheet, s, c):
    sheet.new()
    sheet.h1("Inside the largest topics")
    bottom = s["topics"][TOP_N:]
    sheet.y += 4
    lead = (f"The top {count_word(TOP_N)} topics give {top3(s):.0f}% of the marks. All the other "
            f"topics give {sum(t['marks_pct'] for t in bottom):.0f}%. " if bottom else "")
    # A topic whose first subtopic is 96% of it has no split worth drawing, and neither
    # does one the syllabus never subdivided.
    splittable = [t for t in s["topics"]
                  if t["marks_pct"] >= 1 and len(s["inside"][t["id"]]) > 1
                  and s["inside"][t["id"]][0]["pct"] < 97]
    drawn = splittable[:4]
    # What the bars below show, worked out from those same bars: which topics have most of
    # their marks in one section, and how many sections the others spread across. The typed
    # "Some topics sit in one section. Others spread across four or five" was false on
    # Papers 2, 3 and 4 (ported from Papers Toolkit, P5-BUS-LINT-BUILD).
    mostly = [t for t in drawn if s["inside"][t["id"]][0]["pct"] > MOSTLY_PCT]
    counts = [sum(1 for i in s["inside"][t["id"]] if i["pct"] > 0)
              for t in drawn if t not in mostly]
    span = f"{span_words(min(counts), max(counts))} sections" if counts else ""
    if not drawn:
        how = ""
    elif mostly and counts:
        how = (f"Each bar below divides a topic into its syllabus sections. Some have more than "
               f"{MOSTLY_PCT}% of their marks in a single section. Others spread across {span}, "
               "and then you cannot revise a part of the chapter and stop.")
    elif counts:
        how = (f"Each bar below divides a topic into its syllabus sections. Each one spreads "
               f"across {span}, so you cannot revise a part of the chapter and stop.")
    else:
        how = (f"Each bar below divides a topic into its syllabus sections. Each one has more "
               f"than {MOSTLY_PCT}% of its marks in a single section.")
    if lead or how:
        callout(sheet, "How to read this", (lead + how).strip())
    sheet.y += 2
    for t in drawn:
        sheet.need(76)
        sheet.page.insert_text((L, sheet.y), t["name"], fontname="hebo", fontsize=9.6,
                               color=INK)
        sheet.page.insert_text((R - 86, sheet.y),
                               f"{t['marks_pct']:.0f}% of the paper", fontname="helv",
                               fontsize=8, color=MUTED)
        sheet.y += 12
        stacked(sheet, [(i["name"], i["pct"]) for i in s["inside"][t["id"]]],
                keep=4, rest="The other sections")

    sheet.h2("If you have little time, revise in this order")
    order = [t for t in s["topics"] if t["marks_pct"] >= 1][:7]
    for i, t in enumerate(order, 1):
        sheet.need(16)
        sheet.page.insert_text((L, sheet.y), f"{i}.", fontname="hebo", fontsize=9,
                               color=ACCENT)
        sheet.page.insert_text((L + 16, sheet.y), t["name"], fontname="helv", fontsize=9.4,
                               color=INK)
        sheet.page.insert_text((L + 210, sheet.y),
                               f"{t['marks_pct']:.0f}% of marks, in {t['appears_pct']:.0f}% of papers",
                               fontname="helv", fontsize=8.4, color=MUTED)
        sheet.y += 15
    sheet.y += 4
    # Worked out from the list, not typed: Paper 1's first topic below the list is
    # modelling at 5.1%, which a flat "less than 5%" got wrong.
    rest = [t["marks_pct"] for t in s["topics"] if t not in order]
    tail_note = ("" if not rest else
                 f" Each topic below this list gives less than {math.floor(max(rest)) + 1}% "
                 "of the marks. Learn them after you know the topics above.")
    order_note = "The order uses the marks first, then how often the topic appears." + tail_note
    # The cover promises these topics are "named on the next page". They go at the end of
    # the note above when no name breaks across two lines there, else on a line of their
    # own (a whole extra line can push the last syllabus section off this page). The build
    # refuses if the names slide onto page 3 or a name still wraps.
    small = small_topics(s)
    if not small:
        sheet.note(order_note)
    else:
        names = [t["name"] for t in small]
        line = (f"{names[0]} gives less than {SMALL_PCT}% of the marks." if len(names) == 1
                else f"Less than {SMALL_PCT}% of the marks each: " + "; ".join(names) + ".")
        whole = lambda txt: all(any(n in ln for ln in wrap(txt, CW, 8.6)) for n in names)
        notes = [f"{order_note} {line}"] if whole(f"{order_note} {line}") else [order_note, line]
        first = sheet.n
        for n_ in notes:
            sheet.note(n_)
        assert first == sheet.n == 2 and whole(notes[-1]), (
            f"Paper {s['paper']}: sub-{SMALL_PCT}% topics not named whole on page 2: {notes[-1]}")

    any_hint = False
    sheet.h2("The syllabus sections with the most marks")
    for sub in s["subtopics"][:9]:
        if sheet.y + 46 > 794:   # never push this list onto a page of its own
            break
        sheet.page.insert_text((L, sheet.y), sub["id"], fontname="hebo", fontsize=8.6,
                               color=ACCENT)
        sheet.page.insert_text((L + 30, sheet.y), fit(sub["name"], 200, 9), fontname="helv",
                               fontsize=9, color=INK)
        hint, kept = "", []
        for th in sub["themes"]:
            trial = ", ".join(kept + [th.replace(" & ", " and ")])
            if pymupdf.get_text_length(trial, fontname="helv", fontsize=7.8) > 196:
                break
            kept.append(th.replace(" & ", " and "))
        hint = ", ".join(kept)
        if hint:
            any_hint = True
            sheet.page.insert_text((L + 240, sheet.y), hint, fontname="helv",
                                   fontsize=7.8, color=FAINT)
        sheet.page.insert_text((R - 26, sheet.y), f"{sub['pct']:.0f}%", fontname="hebo",
                               fontsize=8.6, color=INK)
        sheet.y += 15
    sheet.y += 2
    tail = (" The grey text shows the content of those questions." if any_hint else "")
    sheet.note("The percentages are a share of the whole paper." + tail)


def page_grades(sheet, s, c):
    sheet.new()
    sheet.h1("What each grade needs")
    g = s["grade_pct"]
    sheet.note("Cambridge sets the boundary after it marks the papers. The boundary moves with "
               "the results of that sitting. The chart shows the published figures for every "
               f"session since {s['thresholds'][0]['year']}, as a percentage of the paper.")
    sheet.y += 10
    tiles(sheet, [(f"{g['A']:.0f}%", f"for an A, about {s['grade_raw']['A']:.0f} of {s['max_now']} marks"),
                  (f"{g['C']:.0f}%", f"for a C, about {s['grade_raw']['C']:.0f} marks"),
                  (f"{g['E']:.0f}%", f"for an E, about {s['grade_raw']['E']:.0f} marks")],
          height=78)
    n_recent = count_word(len(s["recent"]))
    sheet.note(f"The average of the last {n_recent} sittings.")
    sheet.y += 12
    line_chart(sheet, s["thresholds"], [("A", ACCENT), ("C", GOLD), ("E", WARN)])
    callout(sheet, "What this means for you", txt(c["threshold_note"], s))
    sheet.h2(f"The last {n_recent} sittings, in raw marks")
    table(sheet, ["Session", "Out of", "A", "B", "C", "D", "E"],
          [[f"{r['session']} {r['year']}", r["max"]] +
           [f"{r['raw'][g]:.0f}" for g in "ABCDE"] for r in s["recent"]],
          [120, 60, 46, 46, 46, 46, 46])
    # Sessions with no boundary row, worked out from the series. "Did not publish" is said
    # only when no grade-threshold PDF for that session was downloaded; a PDF on disk with
    # no row is a parsing fault, and the build stops on it.
    gaps = s["threshold_gaps"]
    for name in gaps:
        season, year = name.split()
        assert gt_pdf(int(year), season) is None, (
            f"Paper {s['paper']}: {name} has a grade-threshold PDF but no boundary row")
    gap = ("" if not gaps else
           f" {gaps[0]} is the only gap, because Cambridge did not publish it." if len(gaps) == 1
           else f" {', '.join(gaps[:-1])} and {gaps[-1]} are the only gaps, because Cambridge "
                "did not publish them.")
    sheet.note("Cambridge publishes a boundary for each variant. This table gives their "
               "average." + gap)


def page_shape(sheet, s, c):
    sheet.new()
    practical = s["paper"] in ("2", "4")
    sheet.h1("The shape of the paper")
    sheet.note(txt(c["shape_note"], s))
    sheet.y += 10
    if practical:
        sheet.h2("The most common task sizes")
        top8 = s["sizes"][:8]
        bar_rows(sheet, [(marks_label(x["marks"]), x["pct"], "") for x in top8],
                 label_w=80, track=220)
        sheet.note(f"These sizes give {sum(x['pct'] for x in top8):.0f}% of the tasks. The other "
                   "sizes are rare.")
        sheet.h2("Average marks by task number")
        order = sorted(s["qnum_avg_marks"].items())[:10]
        bar_rows(sheet, [(f"Task {k}", v, "") for k, v in order],
                 label_w=80, track=220, fmt="{:.0f} marks", color=GOLD)
        sheet.note("The marks are at the start of the paper. Divide your time by marks, not by "
                   "the number of tasks.")
        sheet.h2("Where students lose marks")
        for name, why in LEAKS:
            lines = wrap(why, CW - 154, 8.8)
            sheet.need(13 * len(lines) + 8)
            sheet.page.insert_text((L, sheet.y), name, fontname="hebo", fontsize=8.8, color=WARN)
            yy = sheet.y
            for ln in lines:
                sheet.page.insert_text((L + 150, yy), ln, fontname="helv", fontsize=8.8,
                                       color=MUTED)
                yy += 12
            sheet.y = yy + 7
    else:
        sheet.h2("What the questions ask you to do")
        top = s["commands"][:5]
        rest = 100 - sum(c2["pct"] for c2 in top)
        bar_rows(sheet, [(c2["word"], c2["pct"], "") for c2 in top] +
                 [("Everything else", rest, "")], label_w=100, track=220)
        others = [w["word"] for w in s["commands"][5:] if w["word"] != "Other"][:7]
        sheet.note(", ".join(others) + " and the others give the remainder.")
        sheet.h2("How big the questions are")
        bar_rows(sheet, [(marks_label(x["marks"]), x["pct"], "") for x in s["sizes"][:6]],
                 label_w=100, track=220, color=GOLD)
        h, m = (int(x) for x in s["length"].replace("h", "").replace("m", "").split())
        minutes = h * 60 + m
        per = minutes / s["max_now"]
        # The size that carries the most marks, not the most common one. On Paper 1,
        # 6-mark questions are the most common but 8-mark questions carry more marks.
        big = max((x["marks"] for x in s["sizes"]),
                  key=lambda k: k * next(x["pct"] for x in s["sizes"] if x["marks"] == k))
        mins = round(big * per * 2) / 2
        callout(sheet, "Timing",
                f"The paper gives {minutes} minutes for {s['max_now']} marks. That is "
                f"{per * 60:.0f} seconds for each mark. More marks are in {big}-mark questions "
                f"than in any other size, and each one is {mins:g} minutes of work. If you "
                f"write for longer, you will not have the time you need at the end.")
        sheet.h2("What each command word is asking for")
        table(sheet, ["Word", "What they want", "Shape of the answer"],
              CHEAT, [126, 226, 160], size=8.6)
        sheet.note(f"These definitions come from page {s['command_words_page']} of the syllabus. "
                   "The examiner reports repeat the same instruction each series: answer the "
                   "command word that the question uses.")


def page_change(sheet, s, c):
    sheet.new()
    sheet.h1("What has changed")
    sheet.note(f"The chart shows how often each topic appears. The grey dot is the "
               f"{s['papers'] - s['papers_since_2022']} papers before the {syl(s)} syllabus change. The "
               f"coloured dot is the {s['papers_since_2022']} papers after it. The count uses papers, "
               f"not marks, because Cambridge changed how it divides the marks.")
    sheet.y += 12
    movers = [x for x in s["shift"] if max(x["then"], x["now"]) >= 10][:5]
    movers += [x for x in s["shift"][::-1] if max(x["then"], x["now"]) >= 10][:4]
    seen, rows = set(), []
    for m in movers:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        rows.append((clip(m["name"], 32), m["then"], m["now"]))
    dumbbell(sheet, rows, track=196)
    if s["retired"]:
        head = (f"This topic has not appeared since {syl(s)}: " if len(s["retired"]) == 1
                else f"These topics have not appeared since {syl(s)}: ")
        sheet.note(head + ", ".join(s["retired"]) + ".")

    y26 = s["y2026"]
    if y26:
        sheet.h2(f"The {y26_name(s)} paper")
        parts = [(m["name"], m["pct"]) for m in s["y2026_mix"]]
        stacked(sheet, parts, rest="The other topics")
        sheet.note("One paper is not a trend. This paper is here because it is the most recent "
                   "one, and you must know what it contains.")
        sheet.need(30 + 14 * len(y26["questions"]))
        sheet.h2("Every question in that paper")
        table(sheet, ["Q", "Marks", "What it asked about"],
              [[q["q"], q["marks"], q["what"]] for q in y26["questions"]],
              [40, 48, 395], size=8.2)
        biggest = s["y2026_mix"][0]
        in26 = {m["id"] for m in s["y2026_mix"]}
        absent = [t2["name"] for t2 in s["topics"]
                  if t2["appears_pct"] >= USUAL_PCT and t2["id"] not in in26]
        gone = ("This paper contains all the usual topics."
                if not absent else
                (f"This topic is in at least {USUAL_PCT}% of all papers, but it is not in this one: "
                 if len(absent) == 1 else
                 f"These topics are in at least {USUAL_PCT}% of all papers, but they are not in "
                 "this one: ") + ", ".join(absent) + ".")
        callout(sheet, "Reading the newest paper",
                f"{biggest['name']} was the largest part of this paper at {biggest['pct']:.0f}%. {gone} "
                "Use the topic order as a priority list. It is not a prediction, because any "
                "single paper can miss a large topic.", color=GOLD)


def page_advice(sheet, s, c):
    sheet.new()
    sheet.h1("What to do about it")
    sheet.note(f"{cap(count_word(len(c['advice'])))} actions, in order of importance.")
    sheet.y += 12
    for i, (title, body) in enumerate(c["advice"], 1):
        lines = wrap(txt(body, s), CW - 28, 9.8)
        sheet.need(28 + 14 * len(lines))
        sheet.page.draw_circle((L + 7, sheet.y - 3.2), 8.4, color=None, fill=tint(ACCENT, 0.88))
        sheet.page.insert_text((L + 4.4 if i < 10 else L + 2.0, sheet.y - 0.2), str(i),
                               fontname="hebo", fontsize=9, color=ACCENT)
        sheet.page.insert_text((L + 28, sheet.y), txt(title, s), fontname="hebo", fontsize=10.4,
                               color=INK)
        sheet.y += 16
        for ln in lines:
            sheet.page.insert_text((L + 28, sheet.y), ln, fontname="helv", fontsize=9.8,
                                   color=MUTED)
            sheet.y += 14
        sheet.y += 13


def _short(sitting):
    """"November 2025" -> "Nov 2025". The right-hand note has 100 points to work in."""
    season, year = sitting.split()
    return f"{season[:3]} {year}"


def _tasks(qs):
    """['1', '4', '5'] -> 'Tasks 1, 4 and 5'."""
    if len(qs) == 1:
        return f"Task {qs[0]}"
    return "Tasks " + ", ".join(qs[:-1]) + " and " + qs[-1]


def repeat_block(sheet, s):
    """The questions Cambridge has set twice, and the variants that are one paper."""
    sheet.h2("Questions that come back")
    if s["repeats"]:
        sheet.note("These parts were set again in a later sitting, in the same words. The "
                   "files or the scenario around them can change. Work the older one, then "
                   "mark yourself against the newer mark scheme.")
        table(sheet, ["Set in", "The question, in the same words"],
              [[re.sub(r"\b(January|March|June|November)\b", lambda m: m.group(1)[:3],
                       r["where"]), r["stem"]] for r in s["repeats"]],
              [156, 327], size=8.2)
    else:
        sheet.note("No part of this paper has been set again, in the same words, in a later "
                   "sitting. Practice on this paper buys you speed and technique. It does not "
                   "buy you the answer.")
    # A "0 of 12 sittings" line is a null result dressed as a warning.
    if s["twins"] and s["twins"]["same"]:
        t = s["twins"]
        sheet.note(f"Variants {t['a']} and {t['b']} of the same sitting were the same "
                   f"paper in {t['same']} of {t['of']} sittings. Check the first page "
                   f"against a paper you have already done before you spend an hour "
                   f"on it.")


def page_payoff(sheet, s, c):
    sheet.new()
    sheet.h1("How far your revision gets you")
    sheet.note("Revise the topics in the order below, largest first. Each bar is the "
               "running total of the marks, not the topic on its own. The dashed lines "
               "are the A, C and E boundaries of the recent sittings. The bars assume "
               "full marks on every topic above, so they are the best case.")
    sheet.y += 14
    rungs = [r for r in s["ladder"] if r["pct"] >= 1][:11]
    rec = s["recency"]
    rows = []
    for t, r in zip(s["topics"], rungs):
        hit = rec.get(t["id"])
        note = ("" if not hit else
                f"{_short(hit['last'])}  ·  {hit['recent']} of last {hit['of']}")
        rows.append((r["name"], r["cum"], note))
    ladder_chart(sheet, rows, s["max_now"], [(g, s["grade_pct"][g]) for g in "ACE"])
    # One window for every row, the one recency() counted over.
    window = {h["of"] for h in rec.values()}
    assert len(window) == 1, f"Paper {s['paper']}: recency windows differ: {window}"
    sheet.note("The right-hand column is when the topic last appeared, and how many of "
               f"the last {count_word(window.pop())} sittings contained it.")

    need = s["ladder_need"]
    n = need["A"]["topics"] or len(s["ladder"])
    reach = s["ladder"][n - 1]
    sheet.y += 4
    callout(sheet, "The arithmetic",
            f"The {n} largest topics give {reach['cum']:.0f}% of the marks. That is "
            f"{reach['marks']:.0f} of {s['max_now']}. An A needs {need['A']['raw']:.0f} "
            f"marks and a C needs {need['C']['raw']:.0f}. "
            + ("Nobody gets every mark on a topic they revised, so add "
               f"{n_of(EXTRA_TOPICS, 'topic')} to whichever line you are aiming at."
               if n + EXTRA_TOPICS <= len(s["ladder"]) else
               "Nobody gets every mark on a topic they revised, so do not leave any topic "
               "on this list out."))

    # A topic share tells a practical candidate nothing about which button to press,
    # so the operation counts sit on the same page as the ladder they qualify.
    if not s["skills"]:
        repeat_block(sheet, s)
        return
    sk = s["skills"]
    sheet.h2("The operations the tasks ask for")
    sheet.note(txt(c["skills_note"], s))
    bar_rows(sheet, [(x["name"], x["papers"] / sk["sittings"] * 100,
                      f"{x['papers']} of {sk['sittings']} sittings")
                     for x in sk["skills"]],
             label_w=176, track=142, row_h=18)


def page_skills(sheet, s, c):
    """Papers 2 and 4 only: the formulae, and the tasks worth working twice."""
    sk = s["skills"]
    sheet.new()
    sheet.h1("What to practise")
    sheet.h2("The functions the mark schemes write out")
    sheet.note("Question papers ask for a result. Mark schemes sometimes print the "
               "formula that produces it. These are the functions they print, grouped "
               "the way you would revise them. The count is every sitting that names "
               "one. It is a floor: a mark scheme that describes the answer in words "
               "instead is not counted.")
    table(sheet, ["Sittings", "Group", "The functions named"],
          [[f["papers"], f["name"], ", ".join(f["members"])] for f in sk["families"]],
          [56, 168, 259], size=8.2)
    sheet.y += 4
    callout(sheet, "How to use these two pages",
            "Take the operations at the top of the chart on the previous page. Do "
            "each one until "
            "you can do it without the menu. Then take the function groups in order. "
            "Every function in a group behaves the same way, so learning one teaches "
            "you the rest.", color=GOLD)

    tm = s["task_map"]
    sheet.h2("What each task position usually is")
    if len({t["name"] for t in tm}) > 2 and max(t["pct"] for t in tm) >= 40:
        firm = [str(t["q"]) for t in tm if t["pct"] >= FIRM_PCT]
        loose = [str(t["q"]) for t in tm if t["pct"] < FIRM_PCT]
        sheet.note(f"Every sitting from {s['task_years'][0]} to {s['task_years'][1]}, by task "
                   "number. The share is how many "
                   "of the sittings with that task used it for that topic. "
                   + (f"{_tasks(firm)} carry the same topic in {FIRM_PCT}% of the sittings or "
                      "more. " if firm else "")
                   + (f"{_tasks(loose)} change more from sitting to sitting. " if loose else "")
                   + "Use the table as a guide, and read every task and its marks before "
                   "you start.")
        table(sheet, ["Task", "Usually", "Share", "Sittings with this task"],
              [[t["q"], t["name"], f"{t['pct']:.0f}%", t["n"]] for t in tm],
              [50, 210, 60, 219], size=8.2)
    else:
        # Over every position, not just the six in tm (task_strongest), and the page
        # says which positions were compared when some were left out.
        top = s["task_strongest"]
        assert (top["q"], top["hits"], top["n"]) in top["compared"] and \
            top["hits"] / top["n"] == max(h / n for _q, h, n in top["compared"]) and \
            all(top["hits"] / top["n"] >= t["hits"] / t["n"] for t in tm
                if t["q"] in top["counted"]) and \
            [q for q, _h, n in top["compared"] if n >= top["need"]] == top["counted"], \
            "strongest task position is not the largest share among the positions compared"
        counted = top["counted"]
        if counted != top["positions"]:
            run = counted == list(range(counted[0], counted[-1] + 1)) and len(counted) > 2
            which = (f"tasks {counted[0]} to {counted[-1]} are" if run else
                     _tasks([str(q) for q in counted]).lower()
                     + (" are" if len(counted) > 1 else " is"))
            scope = (f" Only {which} counted: each of the others is in fewer than "
                     f"{top['need']} of the {top['sittings']} sittings.")
        else:
            scope = ""
        sheet.note(f"The task numbers on this paper do not carry a fixed topic. The "
                   f"strongest position is task {top['q']}, and even there the usual "
                   f"topic, {top['name'].lower()}, is in only {top['hits']} of the "
                   f"{top['n']} sittings.{scope} Read every task and its marks before "
                   f"you start.")
    repeat_block(sheet, s)


STAMP = "inputs-fingerprint:"


def build(paper):
    s = stats(paper)
    stamp = STAMP + fingerprint(report_inputs(paper))
    c = COPY[paper]
    sheet = Sheet(f"9626 Paper {paper} · {s['kind']} · what the past papers show")
    cover(sheet, s, c)
    page_topics(sheet, s, c)
    page_grades(sheet, s, c)
    page_shape(sheet, s, c)
    page_change(sheet, s, c)
    page_payoff(sheet, s, c)
    if s["skills"]:
        page_skills(sheet, s, c)
    page_advice(sheet, s, c)
    out = OUT / f"Paper {paper} - {s['kind']}.pdf"
    sheet.doc.set_metadata({"title": f"CAIE 9626 Paper {paper}: what the past papers show",
                            "author": "past paper vault", "keywords": stamp})
    sheet.doc.save(out, deflate=True, garbage=3)
    sheet.doc.close()
    return out, sheet.n


def check(reports):
    """Exit status 1 if any report PDF was not built from the current inputs."""
    stale = 0
    for paper, (kind, *_rest) in PAPER_META.items():
        f = Path(reports) / f"Paper {paper} - {kind}.pdf"
        want = STAMP + fingerprint(report_inputs(paper))
        got = None
        if f.exists():
            with pymupdf.open(f) as doc:
                got = (doc.metadata or {}).get("keywords")
        ok = got == want
        stale += not ok
        print(f"{'current' if ok else 'STALE  '}  {f.name}"
              + ("" if ok else "  (rebuild: scripts/analyze.py, then build_report_pdf.py)"))
    return 1 if stale else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--check" in args:
        reports = args[args.index("--reports") + 1] if "--reports" in args else OUT
        sys.exit(check(reports))
    for p in args or list("1234"):
        path, pages = build(p)
        print(f"{path.name}  ({pages} pages)")
