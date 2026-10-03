"""Everything the PDF reports print, as percentages.

Topic and subtopic shares are recomputed here from data/question_bank.json plus the
tagging manifests, because those are tagged per *part* — 1(a) and 1(b) can sit under
different topics — and a share worked out at whole-question level quietly attributes
one part's marks to the other part's topic. Command words, near-duplicates, question
sizes and the theme breakdowns come from data/analysis_p*.json, which analyze.py
builds off the same two files.

Two eras, because the syllabus was cut in 2022 and the papers were re-cut with it.
Anything a candidate sitting in 2026 should act on comes from the 2022-onwards slice;
the nine-year figure is there for context and for spotting drift.

March 2026 is folded in from data/y2026_tags.json. Its mark scheme is not published
yet, so it contributes to the marks picture and to nothing else.
"""
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
COMPONENTS = {"1": ["11", "12", "13"], "2": ["02"], "3": ["31", "32", "33"], "4": ["04"]}
SEASON_ORDER = {"March": 0, "June": 1, "November": 2}
CURRENT_SYLLABUS_FROM = 2022
# Which slice the headline numbers come from. The theory papers were re-cut with the
# 2022 syllabus, so anything older describes a different exam. The practicals were not:
# topics 8-11 and 17-21 came through the trim intact, and only six or seven practical
# sittings since 2022 survive the mark-reconciliation check, which is too thin to rank
# a topic on. So they use the whole run.
HEADLINE_FROM = {"1": 2022, "2": 2017, "3": 2022, "4": 2017}
PAPER_META = {
    "1": ("Theory", "1h 45m", "AS", "sections 1-11"),
    "2": ("Practical", "2h 30m", "AS", "sections 8-11"),
    "3": ("Advanced Theory", "1h 45m", "A Level", "sections 12-21"),
    "4": ("Advanced Practical", "2h 30m", "A Level", "sections 17-21"),
}
CODE = re.compile(r"9626_([msw])(\d\d)_qp_(\d+)")
# Cambridge's published command words, longest first so "Compare and contrast" wins.
# They are always capitalised sentence-openers in Cambridge's house style, so a plain
# case-sensitive match beats trying to anchor on punctuation the papers do not have.
COMMAND_WORDS = sorted(
    ["Analyse", "Compare and contrast", "Compare", "Contrast", "Define", "Describe",
     "Discuss", "Evaluate", "Explain", "Identify", "Justify", "State", "Suggest",
     "Choose", "Complete", "Draw", "Give", "Assess"], key=len, reverse=True)
CMD_RE = re.compile(r"\b(" + "|".join(COMMAND_WORDS) + r")\b")
# fallback only: "Using the data in the table, describe ..." has no capitalised word
CMD_ANY = re.compile(CMD_RE.pattern, re.I)


# ---- freshness: a report must never be drawn from inputs older than the tags ----
# The 28 Sep 2026 reports went out stale: the tags changed on 30 Sep, nobody re-ran
# analyze.py or the build, and 123 printed figures were wrong. So analyze.py records a
# fingerprint of what it read, stats() refuses an analysis file whose fingerprint no
# longer matches, and build_report_pdf.py stamps each PDF with the fingerprint of its
# own inputs so `build_report_pdf.py --check` can tell a stale PDF from a current one.

def fingerprint(files):
    """sha256 over the names and bytes of the files, in the order given."""
    h = hashlib.sha256()
    for f in files:
        f = Path(f)
        h.update(f.name.encode() + b"\0")
        h.update(f.read_bytes() if f.exists() else b"<missing>")
        h.update(b"\0")
    return h.hexdigest()


def analysis_inputs(paper, data=None):
    """Everything analyze.py reads to write analysis_p{paper}.json, itself included."""
    data = Path(data or DATA)
    return ([data / "question_bank.json", data / "taxonomy.json"]
            + sorted(data.glob("tagging_manifest_p*.jsonl"))
            + sorted((ROOT / "Text" / f"Paper {paper}").glob("*.md"))
            + [Path(__file__).with_name("analyze.py")])


def report_inputs(paper):
    """Everything a Reports/Paper N PDF is built from: data and the two code files."""
    names = ["question_bank.json", "taxonomy.json", f"tagging_manifest_p{paper}.jsonl",
             f"analysis_p{paper}.json", "y2026_tags.json", "grade_thresholds.json",
             "practical_skills.json"]
    here = Path(__file__).parent
    # Copy facts the pages print from outside data/: the command-word page of the syllabus,
    # the examiner reports counted for the bullet-point advice, the question-paper texts
    # whose sittings bound the practical skill counts.
    extra = ([ROOT / "syllabus2026.md"]
             + sorted((ROOT / "Text" / "Examiner Reports").glob("*.md"))
             + sorted((ROOT / "Text" / f"Paper {paper}").glob("*_qp_*.md")))
    return ([DATA / n for n in names] + extra
            + [here / "report_stats.py", here / "build_report_pdf.py"])


def load_analysis(paper):
    """analysis_p{paper}.json, refused if it was not built from the current inputs."""
    f = DATA / f"analysis_p{paper}.json"
    a = json.loads(f.read_text())
    want = fingerprint(analysis_inputs(paper))
    if a.get("inputs_sha256") != want:
        raise SystemExit(f"{f.name} is stale: its inputs (bank, tags, taxonomy, Text/Paper "
                         f"{paper}, analyze.py) changed since it was written. Run "
                         f"`python3 scripts/analyze.py {paper}` first.")
    return a


def _pct(part, whole):
    return 0.0 if not whole else part / whole * 100


def paper_of(variant):
    return variant[1] if variant[0] == "0" else variant[0]


def stated_total(year, paper):
    if paper in ("1", "3"):
        return 90 if year < 2022 else 70
    return 110 if year < 2022 else 90


def units(paper, keep_short=False):
    """Every tagged question part on this paper.

    Papers whose extracted part marks do not add up to Cambridge's stated total are
    dropped. That only happens on the practicals, where the question paper prints a
    mark for a task but not for each of its steps, and leaving them in would report
    a 38-mark database build as a 1-mark question. The count of what was dropped is
    reported rather than buried.
    """
    rows = [r for r in json.loads((DATA / "question_bank.json").read_text())
            if paper_of(CODE.match(r["paper"]).group(3)) == paper]
    tags = {}
    for line in (DATA / f"tagging_manifest_p{paper}.jsonl").read_text().splitlines():
        if line.strip():
            e = json.loads(line)
            tags[e["id"]] = e["topics"]
    # A question reprinted in another variant is tagged once, where it first appears,
    # and 'dupe_of' points there. It still counts on the paper that reprinted it, so a
    # variant that shares a few questions with another keeps its full size. A variant
    # reprinted whole is the same exam twice, so it is left out rather than counted as
    # a second paper.
    reprint = defaultdict(list)
    for r in rows:
        reprint[r["paper"]].append("dupe_of" in r)
    # Half or more flagged counts as a whole reprint: extraction noise (a stray footer,
    # a split table) stops some parts of a true reprint matching word for word.
    # November 2025 variant 13 has 21 of its 23 parts flagged, so it is left out.
    whole_reprint = {p for p, flags in reprint.items() if sum(flags) >= len(flags) / 2}
    out = []
    for u in rows:
        topics = tags.get(f"{u['paper']}:{u['q']}{u['part'] or ''}") or tags.get(u.get("dupe_of"))
        if not topics or u["paper"] in whole_reprint:
            continue
        season, yy, variant = CODE.match(u["paper"]).groups()
        text = "\n".join(x for x in (u["stem"], u["part_stem"], u["text"]) if x)
        own = [x for x in (u["text"], u["part_stem"], u["stem"]) if x]
        out.append({"paper": u["paper"], "q": u["q"], "year": 2000 + int(yy),
                    "season": season, "marks": u["marks"] or 0,
                    "topics": topics, "text": text, "own": own})
    for q in y2026(paper)["questions"] if y2026(paper) else []:
        out.append({"paper": y2026(paper)["code"], "q": q["q"].split("(")[0], "year": 2026,
                    "season": "m", "marks": q["marks"], "topics": q["tags"],
                    "text": q["what"], "own": []})
    if keep_short:
        return out
    per = Counter()
    for r in out:
        per[(r["paper"], r["year"])] += r["marks"]
    whole = {p for (p, y), m in per.items() if m == stated_total(y, paper)}
    return [r for r in out if r["paper"] in whole]


def sizes(rows, by_question):
    """Distribution of part sizes, or of whole-question sizes with parts summed."""
    if by_question:
        per = Counter()
        for r in rows:
            per[(r["paper"], r["q"])] += r["marks"]
        vals = Counter(v for v in per.values() if v)
    else:
        vals = Counter(r["marks"] for r in rows if r["marks"])
    n = sum(vals.values())
    return [{"marks": k, "pct": _pct(v, n)} for k, v in vals.most_common()]


def questions_per_paper(rows):
    """Lowest and highest number of numbered questions in one paper, over the papers in
    rows, plus the papers at the lowest count (D19, printed as min to max).

    Counted twice: from the tagged units, and from every part of the same papers in
    question_bank.json (tagged or not). A question whose parts all lost their tags would
    vanish from the first count only, so the two must agree or the build stops.
    """
    per = defaultdict(set)
    for r in rows:
        per[r["paper"]].add(str(r["q"]))
    raw = defaultdict(set)
    for u in json.loads((DATA / "question_bank.json").read_text()):
        if u["paper"] in per:
            raw[u["paper"]].add(str(u["q"]))
    for p, qs in raw.items():
        assert qs == per[p], f"{p}: questions in the bank {sorted(raw[p])} != tagged units {sorted(per[p])}"
    counts = {p: len(qs) for p, qs in per.items()}
    lo, hi = min(counts.values()), max(counts.values())
    return {"min": lo, "max": hi, "papers": len(counts),
            "fewest": sorted(p for p, n in counts.items() if n == lo)}


TASK_NO = re.compile(r"^\s*(\d+)")


def tasks_per_paper(rows):
    """Lowest and highest number of tasks in one paper, over the papers in rows (D29,
    printed as min to max), plus the highest task number and the papers at each end.

    A task is a numbered question that carries marks: Task 1a and Task 1b are both
    Task 1, and a numbered step with no marks (June 2019 Question 7, "Save your
    Evidence Document.") is not a task.

    Counted twice: from the tagged units, and from every part of the same papers in
    question_bank.json (tagged or not), so a task whose parts lost their tags stops
    the build instead of shrinking the count.
    """
    def per_paper(items):
        out = defaultdict(lambda: defaultdict(float))
        for paper, q, m in items:
            out[paper][int(TASK_NO.match(str(q)).group(1))] += m or 0
        return {p: {n for n, v in t.items() if v > 0} for p, t in out.items()}

    per = per_paper((r["paper"], r["q"], r["marks"]) for r in rows)
    raw = per_paper((u["paper"], u["q"], u["marks"])
                    for u in json.loads((DATA / "question_bank.json").read_text())
                    if u["paper"] in per)
    for p, ts in raw.items():
        assert ts == per[p], f"{p}: tasks in the bank {sorted(ts)} != tagged units {sorted(per[p])}"
    counts = {p: len(ts) for p, ts in per.items()}
    lo, hi = min(counts.values()), max(counts.values())
    last = max(max(ts) for ts in per.values())
    assert last == hi, f"highest task number {last} != most tasks in a paper {hi}"
    return {"min": lo, "max": hi, "last": last, "papers": len(counts),
            "fewest": sorted(p for p, n in counts.items() if n == lo),
            "most": sorted(p for p, n in counts.items() if n == hi)}


def command_word(r):
    """The command word a part counts under: the first one in its own text, a
    capitalised match first, then any case. None for a part with no text of its own
    (March 2026 has only a summary line per question)."""
    if not r["own"]:
        return None
    return (next((m.group(1) for t in r["own"] for m in [CMD_RE.search(t)] if m), None)
            or next((m.group(1).capitalize() for t in r["own"]
                     for m in [CMD_ANY.search(t)] if m), "Other"))


def command_words(rows):
    """Share of the marks each command word asks for, not how often it appears: a
    2-mark Identify and an 8-mark Discuss are not the same amount of paper. A part
    counts once, under the first command word in its own text. March 2026 has only a
    summary line per question, so it is left out."""
    c = Counter()
    for r in rows:
        hit = command_word(r)
        if hit is not None:
            c[hit] += r["marks"]
    n = sum(c.values())
    return [{"word": w, "pct": _pct(k, n)} for w, k in c.most_common()], n


def command_word_sizes(rows):
    """Which command words the largest parts use (D33, the "do these last" advice).

    Same rule and same parts as command_words(). `top` is the largest part, `words` is
    every command word with its part count, mean and largest part, sorted by how many
    parts at `top` marks it has, then by mean marks. `years` are the first and last
    years of the parts that have text. A "most marks" claim is never typed: the advice
    prints these counts instead.
    """
    by = defaultdict(list)
    years = []
    for r in rows:
        w = command_word(r)
        if w is not None:
            by[w].append(r["marks"])
            years.append(r["year"])
    top = max(m for v in by.values() for m in v)
    words = sorted(({"word": w, "parts": len(v), "mean": mean(v), "max": max(v),
                     "at_top": sum(m == top for m in v)} for w, v in by.items()),
                   key=lambda x: (-x["at_top"], -x["mean"], x["word"]))
    at_top = sum(x["at_top"] for x in words)
    assert at_top == sum(r["marks"] == top for r in rows if r["own"]), "top-part count"
    # every part in the slice, with or without text: the advice checks its "no part
    # is worth more than top" against this
    return {"top": top, "at_top": at_top, "words": words,
            "years": [min(years), max(years)],
            "largest_part": max(r["marks"] for r in rows)}


_Y26 = None


def y2026(paper):
    global _Y26
    if _Y26 is None:
        raw = json.loads((DATA / "y2026_tags.json").read_text())
        _Y26 = {v["paper"]: dict(v, code=k) for k, v in raw.items() if not k.startswith("_")}
    return _Y26.get(paper)


def shares(rows, names, subnames, presence=None):
    """Topic and subtopic shares over one slice of the corpus.

    `rows` carries the marks and is the reconciling set. `presence` answers "did this
    topic turn up at all", so it defaults to the same rows but should be passed the
    unfiltered set: whether a paper asked about mail merge does not depend on whether
    its mark allocations extracted cleanly, and using the filtered set for both once
    reported mail merge as extinct on the strength of three dropped papers.
    """
    presence = rows if presence is None else presence
    marks, submarks = Counter(), Counter()
    for r in rows:
        # A part tagged with two topics splits its marks between them. Adding the full
        # marks to each one inflates the total and every share computed against it: on
        # Paper 4 it put the denominator 9% above the marks that actually exist.
        tops = {tag.split(".")[0] for tag in r["topics"]}
        subs = set(r["topics"])
        for tag in tops:
            marks[tag] += r["marks"] / len(tops)
        for tag in subs:
            submarks[tag] += r["marks"] / len(subs)
    qcount, seen = Counter(), defaultdict(set)
    for r in presence:
        for tag in r["topics"]:
            qcount[tag.split(".")[0]] += 1
            seen[tag.split(".")[0]].add(r["paper"])
    papers = len({r["paper"] for r in presence})
    total = sum(marks.values())
    topics = sorted(
        ({"id": t, "name": names.get(t, t), "marks_pct": _pct(marks.get(t, 0), total),
          "appears_pct": _pct(len(seen[t]), papers), "questions": qcount[t]}
         for t in set(marks) | set(qcount)),
        key=lambda x: (-x["marks_pct"], -x["appears_pct"]))
    inside = defaultdict(list)
    for sub, m in submarks.items():
        inside[sub.split(".")[0]].append({"id": sub, "name": subnames.get(sub, sub), "marks": m})
    for items in inside.values():
        whole = sum(i["marks"] for i in items)
        items.sort(key=lambda i: -i["marks"])
        for i in items:
            i["pct"] = _pct(i["marks"], whole)
    flat = sorted(({"id": s, "name": subnames.get(s, s), "pct": _pct(m, total)}
                   for s, m in submarks.items()), key=lambda s: -s["pct"])
    return {"topics": topics, "inside": inside, "subtopics": flat,
            "papers": papers, "marks": total}


def presence_share(rows):
    """Share of papers in this slice that asked about each topic at all.

    Drift is measured this way rather than by marks or by question count, because both
    of those move with how finely Cambridge numbered the steps that year. Whether a
    topic showed up does not."""
    seen = defaultdict(set)
    for r in rows:
        for tag in r["topics"]:
            seen[tag.split(".")[0]].add(r["paper"])
    n = len({r["paper"] for r in rows})
    return {t: _pct(len(ps), n) for t, ps in seen.items()}


def thresholds(paper):
    """Per-session grade boundaries as a share of the paper, variants averaged."""
    gt = json.loads((DATA / "grade_thresholds.json").read_text())
    rows = []
    for code, sess in gt.items():
        got = [c for k, c in sess["components"].items() if k in COMPONENTS[paper]]
        if not got:
            continue
        rows.append({"code": code, "year": sess["year"], "session": sess["session"],
                     "max": got[0]["max"],
                     "pct": {g: mean(c[g] / c["max"] * 100 for c in got) for g in "ABCDE"},
                     "raw": {g: mean(c[g] for c in got) for g in "ABCDE"}})
    rows.sort(key=lambda r: (r["year"], SEASON_ORDER[r["session"]]))
    return rows


SEASON_NAME = {"m": "March", "s": "June", "w": "November"}


def sitting_of(code):
    """9626_s25_qp_12 -> (2025, 1, 'June 2025'). 2026 rows carry the same shape."""
    season, yy, _ = CODE.match(code).groups()
    year = 2000 + int(yy)
    name = SEASON_NAME[season]
    return year, SEASON_ORDER[name], f"{name} {year}"


def recency(rows, last_n=4):
    """When each topic last came up, and how many of the last `last_n` sittings had it.

    Frequency over nine years answers "is this topic common". It does not answer "is it
    still being set", which is the question a candidate three weeks out is really asking.
    Counted on sittings rather than papers so a three-variant series is not three hits.
    """
    sittings = sorted({sitting_of(r["paper"])[:2] for r in rows}, reverse=True)
    recent = set(sittings[:last_n])
    seen = defaultdict(set)
    for r in rows:
        key = sitting_of(r["paper"])
        for tag in r["topics"]:
            seen[tag.split(".")[0]].add(key)
    out = {}
    for t, hits in seen.items():
        newest = max(hits)
        out[t] = {"last": newest[2], "last_key": newest[:2],
                  "recent": len({h[:2] for h in hits} & recent), "of": len(sittings[:last_n])}
    return out


def _clean_stem(text):
    """The extracted stems carry mark tags and a run-on of the next paragraph."""
    text = text.split("**[")[0]
    text = re.sub(r"\s+", " ", text).strip()
    text = re.split(r"(?<=[.?]) ", text)[0]
    return text


LEAD_IN = re.compile(r"^(You may refer|Refer to|Read |Look at|Use the insert)", re.I)
# Instructions printed in every practical paper. They repeat word for word in every
# sitting and teach nobody anything.
BOILER_PART = re.compile(r"^(Save your|Save this|Save the|Put your|Place your|"
                         r"Make sure|All tasks)", re.I)


def exact_repeats(rows, limit=6):
    """Parts set again in a later sitting in the same words.

    Matched on the part's own wording, not on the whole question: the scenario around
    it changes, so a whole-question similarity pass pairs different questions that
    share a stem and misses the same part under a new stem. Lead-in sentences ("Refer
    to the insert") are dropped first, or every part that opens with one looks like a
    repeat. Ported from the Papers Toolkit.
    """
    seen = defaultdict(set)
    shown = {}
    for r in rows:
        if not r["own"] or r["year"] == 2026:
            continue
        own = r["own"][0]
        if len(r["own"]) > 1 and not own.lstrip()[:1].isupper():
            own = r["own"][1] + " " + own
        text = re.sub(r"\*\*\[\d+\]\*\*|!\[[^\]]*\]\([^)]*\)|\[Total: \d+\]", " ", own)
        # "Evidence 3" is the practical papers' label for the next screenshot
        text = re.sub(r"\bEvidence \d+.*$|(\s+\d)+\s*$", "", text, flags=re.S)
        text = re.sub(r"\s+", " ", text).strip()
        sents = [x for x in re.split(r"(?<=[.?])\s+", text) if x and not LEAD_IN.match(x)]
        stem = " ".join(sents).strip()
        if len(stem.split()) < 5 or BOILER_PART.match(stem):
            continue
        key = re.sub(r"[^a-z0-9]+", " ", stem.lower()).strip()
        seen[key].add(sitting_of(r["paper"]))
        shown.setdefault(key, stem)
    out = []
    for key, sits in seen.items():
        keys = {x[:2] for x in sits}
        if len(keys) < 2:
            continue
        names = [x[2] for x in sorted({x[:2]: x for x in sits}.values())]
        out.append({"stem": shown[key], "n": len(names), "latest": max(keys),
                    "where": (", ".join(names[:-1]) + " and " + names[-1]) if len(names) <= 3
                    else f"{len(names)} sittings, last {names[-1]}"})
    out.sort(key=lambda x: (-x["n"], tuple(-v for v in x["latest"])))
    return out[:limit], len(out)


def repeats(analysis, limit=6):
    """Question stems that have been set twice, near word for word.

    Straight out of the near-duplicate pass. Deduplicated on the stem, because one
    recycled question generates a pair for every sitting it appears in.
    """
    out, seen = [], set()
    for d in analysis["near_duplicates_top20"]:
        stem = _clean_stem(d["a_stem"])
        key = stem.lower()[:40]
        # "Save your Evidence Document" repeats in every paper ever set and teaches
        # nobody anything. Same-sitting pairs are the variant story, not this one.
        if len(stem) < 30 or key in seen or stem.lower().startswith("save your"):
            continue
        one, two = (sitting_of(d[k].split()[0]) for k in "ab")
        if one[:2] == two[:2]:
            continue
        seen.add(key)
        first, second = sorted([one, two])
        out.append({"stem": stem, "where": f"{first[2]} and {second[2]}",
                    "sim": d["similarity"]})
        if len(out) == limit:
            break
    return out


def grade_ladder(topics, grade_raw, max_marks):
    """Revise the topics in order of size. Where do you stand after each one?

    Cumulative share of the paper, converted to marks, against the mean raw boundary
    of the recent sittings. It answers the only question a revision plan has to
    answer: is this list long enough yet? A perfect score on every topic listed is
    assumed, so the ladder is the best case, and the text on the page says so.
    """
    rungs, run = [], 0.0
    for t in topics:
        run += t["marks_pct"]
        rungs.append({"name": t["name"], "pct": t["marks_pct"], "cum": run,
                      "marks": run / 100 * max_marks})
    needed = {}
    for g in "ACE":
        want = grade_raw[g]
        hit = next((i + 1 for i, r in enumerate(rungs) if r["marks"] >= want), None)
        needed[g] = {"raw": want, "topics": hit,
                     "cum": rungs[hit - 1]["cum"] if hit else 100.0}
    return rungs, needed


def variant_twins(paper):
    """Some variants of the same sitting are the same paper with a new cover.

    Read from the bank's reprint flags rather than the text. Word counts put June
    2024's Paper 3 variants 31 and 33 at 0.939, under the 0.95 cut-off, although the
    bank flags the whole of 33 as a reprint. A variant counts as a copy when half or
    more of its parts are flagged as reprints of the other one. Ported from the
    Papers Toolkit.
    """
    rows = [r for r in json.loads((DATA / "question_bank.json").read_text())
            if paper_of(CODE.match(r["paper"]).group(3)) == paper]
    parts, copied = Counter(), Counter()
    for r in rows:
        parts[r["paper"]] += 1
        if "dupe_of" in r:
            copied[(r["dupe_of"].split(":")[0], r["paper"])] += 1
    variants = COMPONENTS[paper]
    if len(variants) < 2:
        return None
    sittings = defaultdict(set)
    for code in parts:
        sittings[code[:-2]].add(code[-2:])
    best = None
    for i, a in enumerate(variants):
        for b in variants[i + 1:]:
            both = [k for k, v in sittings.items() if a in v and b in v]
            if not both:
                continue
            same = sum(copied[(k + a, k + b)] >= parts[k + b] / 2 for k in both)
            row = {"a": a, "b": b, "same": same, "of": len(both)}
            if best is None or same > best["same"]:
                best = row
    return best


def practical_skills(paper):
    """Operation counts for components 02 and 04. See practical_skills.py."""
    f = DATA / "practical_skills.json"
    if not f.exists():
        return None
    return json.loads(f.read_text()).get(paper)


def task_map(rows, names, min_n=10, top=6):
    """Which topic each task position usually carries, counted in sittings.

    A sitting counts once for a task position, and once for a topic at that position
    however many of the task's parts carry it. Counting tagged parts instead put 36
    "sittings" at task 1 on a paper that has 27. The shares can add to more than
    100%, because one task can carry two topics.

    Only positions that most sittings actually have, because task 14 exists in three
    papers and a share worked out on three papers is not a pattern. The caller
    decides whether the answer is worth printing: on a paper whose task order is
    fixed, every position names a different topic; on one that is not fixed, the same
    topic wins several positions at under half, which is the paper's topic share
    showing through and says nothing about the position.
    """
    have, carry = defaultdict(set), defaultdict(lambda: defaultdict(set))
    for r in rows:
        head = re.match(r"\d+", r["q"])
        if not head:
            continue
        q = int(head.group())
        have[q].add(r["paper"])
        for tag in r["topics"]:
            carry[q][tag.split(".")[0]].add(r["paper"])
    out = []
    for q in sorted(have):
        n = len(have[q])
        if n < min_n:
            continue
        tag, hits = max(carry[q].items(), key=lambda kv: (len(kv[1]), -int(kv[0])))
        out.append({"q": q, "n": n, "id": tag, "name": names.get(tag, tag),
                    "pct": _pct(len(hits), n), "hits": len(hits)})
    return out[:top] if top else out


def task_strongest(positions, sittings):
    """The task position whose usual topic holds in the largest share of its sittings.

    Every position counts, not only the first six the table shows: on Paper 2, task 7
    (11 of 21) beats task 1 (13 of 27). A position joins only when at least half of
    the sittings have it, the rule task_map's docstring states ("positions that most
    sittings actually have"). Ties go to the position more sittings have, then the
    lower task number. 'counted' lists the positions compared, so the page can say
    which ones they were, and 'compared' keeps their (task, hits, sittings) for the
    build's check.
    """
    if not positions:
        return None
    need = -(-sittings // 2)                      # at least half, rounded up
    counted = [t for t in positions if t["n"] >= need]
    best = max(counted, key=lambda t: (t["hits"] / t["n"], t["n"], -t["q"]))
    return {**best, "counted": [t["q"] for t in counted], "sittings": sittings,
            "need": need,
            "compared": [(t["q"], t["hits"], t["n"]) for t in counted],
            "positions": [t["q"] for t in positions]}


def dropped(paper):
    """(sittings used, sittings available) after the reconciliation filter."""
    all_papers = {r["paper"] for r in units(paper, keep_short=True)}
    kept = {r["paper"] for r in units(paper)}
    return len(kept), len(all_papers)


# Percentile bands (nearest rank) behind "usually worth X to Y marks" (the middle half of
# the papers that have the topic) and "N% of the tasks are worth X to Y marks" (the middle
# 80%). The page prints the share that actually falls inside, never the band's name.
USUAL_BAND = (25, 75)
WIDE_BAND = (10, 90)


def band(values, lo_q, hi_q):
    """Nearest-rank lo_q and hi_q percentiles of values, and the share of values inside them."""
    v = sorted(values)
    rank = lambda q: v[max(1, math.ceil(q / 100 * len(v))) - 1]
    lo, hi = rank(lo_q), rank(hi_q)
    return {"lo": lo, "hi": hi, "n": len(v), "share": _pct(sum(lo <= x <= hi for x in v), len(v))}


def task_totals(rows):
    """{(paper, question label): marks} with the parts added up, the same unit sizes(rows, True)
    counts, so a band agrees with the task-size bars on the same page. Zero-mark steps are left out."""
    per = defaultdict(float)
    for r in rows:
        per[(r["paper"], str(r["q"]))] += r["marks"]
    return {k: v for k, v in per.items() if v > 0}


def topic_bands(rows, lo_q, hi_q):
    """Per topic: the band of the marks it carries in each paper that has it (split marks, as in
    shares())."""
    per = defaultdict(lambda: defaultdict(float))
    for r in rows:
        tops = {tag.split(".")[0] for tag in r["topics"]}
        for tag in tops:
            per[tag][r["paper"]] += r["marks"] / len(tops)
    return {t: band(list(v.values()), lo_q, hi_q) for t, v in per.items()}


def biggest_task(rows):
    """The largest single task in the slice, where it was set, and the other tasks of that paper."""
    per = task_totals(rows)
    if not per:
        return None
    big = max(per, key=lambda k: (per[k], sitting_of(k[0])[:2]))
    others = [v for (p, q), v in per.items() if p == big[0] and q != big[1]]
    return {"sitting": sitting_of(big[0])[2], "task": big[1], "marks": per[big],
            "lo": min(others) if others else None, "hi": max(others) if others else None}


def then_papers(rows, before):
    """Papers before `before`, and per topic how many of them have it (exact counts)."""
    old = [r for r in rows if r["year"] < before]
    seen = defaultdict(set)
    for r in old:
        for tag in r["topics"]:
            seen[tag.split(".")[0]].add(r["paper"])
    return len({r["paper"] for r in old}), {t: len(p) for t, p in seen.items()}


def er_mentions(paper, pattern, since):
    """Examiner reports from `since` on that say `pattern` about this paper, out of those that
    report on it. A report counts once, whichever of the paper's variants it says it under."""
    hit = of = 0
    for f in sorted((ROOT / "Text" / "Examiner Reports").glob("9626_*_er.md")):
        m = re.match(r"9626_[msw](\d\d)_er$", f.stem)
        if not m or 2000 + int(m.group(1)) < since:
            continue
        parts = re.split(r"^\s*Paper 9626/(\d\d)\s*$", f.read_text(), flags=re.M)
        secs = [parts[i + 1] for i in range(1, len(parts), 2) if parts[i] in COMPONENTS[paper]]
        if secs:
            of += 1
            hit += any(re.search(pattern, s_, re.I) for s_ in secs)
    return {"hit": hit, "of": of, "since": since}


def syllabus_page(heading):
    """Printed page of a syllabus section, read from the contents table of syllabus2026.md."""
    m = re.search(r"^\|" + re.escape(heading) + r"\|(\d+)\|", (ROOT / "syllabus2026.md").read_text(), re.M)
    assert m, f"syllabus2026.md has no contents row for {heading!r}"
    return int(m.group(1))


def qp_years(paper, sittings):
    """First and last year of the question-paper texts practical_skills.py reads. Their count must
    equal the sittings in practical_skills.json, or the skill counts are stale."""
    comp = COMPONENTS[paper][0]
    names = {f.stem[:8] for f in (ROOT / "Text" / f"Paper {paper}").glob(f"*_qp_{comp}.md")}
    assert len(names) == sittings, (
        f"Paper {paper}: {len(names)} question-paper texts, practical_skills.json counts {sittings}; "
        "re-run practical_skills.py")
    years = sorted(2000 + int(n[6:8]) for n in names)
    return [years[0], years[-1]]


def gt_pdf(year, session):
    """The downloaded grade-threshold PDF of a session, or None if there is none on disk."""
    letter = {v: k for k, v in SEASON_NAME.items()}[session]
    f = (ROOT / "PDFs" / "Grade Thresholds").joinpath(f"9626_{letter}{year % 100:02d}_gt.pdf")
    return f if f.exists() else None


def threshold_gaps(gt):
    """Sessions with no boundary row between the first and the newest one, over the seasons
    the series has. The grades page names them, so the missing chart point is explained from
    the data and not from a typed session."""
    if not gt:
        return []
    have = {(r["year"], r["session"]) for r in gt}
    seasons = sorted({r["session"] for r in gt}, key=SEASON_ORDER.get)
    first = (gt[0]["year"], SEASON_ORDER[gt[0]["session"]])
    last = (gt[-1]["year"], SEASON_ORDER[gt[-1]["session"]])
    return [f"{s} {y}" for y in range(gt[0]["year"], gt[-1]["year"] + 1) for s in seasons
            if first <= (y, SEASON_ORDER[s]) <= last and (y, s) not in have]


def stats(paper):
    a = load_analysis(paper)
    tax = json.loads((DATA / "taxonomy.json").read_text())
    names = {k: v["name"] for k, v in tax.items()}
    subnames = {s: n for v in tax.values() for s, n in v["subtopics"].items()}

    rows, every = units(paper), units(paper, keep_short=True)
    era = HEADLINE_FROM[paper]
    now_rows = [r for r in rows if r["year"] >= era]
    now = shares(now_rows, names, subnames, [r for r in every if r["year"] >= era])
    ever = shares(rows, names, subnames, every)

    # March 2026 has summary tags only, no bank entry, so it stays out of the
    # per-task counts.
    task_rows = [r for r in every if r["year"] < 2026]

    # ---- drift: before the 2022 syllabus cut against after ----
    # Always the same split, whatever slice the headline numbers come from.
    then_pct = presence_share([r for r in every if r["year"] < CURRENT_SYLLABUS_FROM])
    now_pct = presence_share([r for r in every if r["year"] >= CURRENT_SYLLABUS_FROM])
    shift = sorted(({"id": t, "name": names.get(t, t),
                     "then": then_pct.get(t, 0.0), "now": now_pct.get(t, 0.0)}
                    for t in set(then_pct) | set(now_pct)),
                   key=lambda s: -(s["now"] - s["then"]))
    # topics the 2022 syllabus cut: present before, gone since
    retired = [s["name"] for s in shift if s["then"] >= 10 and s["now"] == 0]

    commands, cmd_total = command_words(now_rows)
    themes = a.get("themes_by_subtopic", {})
    for s in now["subtopics"]:
        s["themes"] = [k for k, _ in sorted(themes.get(s["id"], {}).items(),
                                            key=lambda kv: -kv[1])[:3]]

    # ---- the newest paper on its own ----
    y26 = y2026(paper)
    mix = []
    if y26:
        m = Counter()
        for q in y26["questions"]:
            tops = {tag.split(".")[0] for tag in q["tags"]}
            for tag in tops:
                m[tag] += q["marks"] / len(tops)
        whole = sum(m.values())
        mix = [{"id": k, "name": names.get(k, k), "pct": _pct(v, whole)}
               for k, v in m.most_common()]

    reps, n_reps = exact_repeats(every)
    gt = thresholds(paper)
    recent = gt[-6:]
    grade_raw = {g: mean(r["raw"][g] for r in recent) for g in "ABCDE"}
    ladder, need = grade_ladder(now["topics"], grade_raw, gt[-1]["max"])
    kind, length, level, scope = PAPER_META[paper]
    newest = max(sitting_of(r["paper"]) for r in every)
    n_then, then_count = then_papers(every, CURRENT_SYLLABUS_FROM)
    skills = practical_skills(paper)
    return {
        "paper": paper, "kind": kind, "length": length, "level": level, "scope": scope,
        "papers": ever["papers"], "papers_now": now["papers"], "questions": len(rows),
        "headline_from": HEADLINE_FROM[paper],
        "sittings": dropped(paper),
        "near_dupes": a["near_duplicate_total_pairs_found"],
        "max_now": gt[-1]["max"],
        "topics": now["topics"], "inside": now["inside"], "subtopics": now["subtopics"],
        "topics_ever": ever["topics"],
        "commands": commands, "cmd_total": cmd_total,
        "command_sizes": command_word_sizes(now_rows),
        "sizes": sizes(now_rows, by_question=True),
        "part_sizes": sizes(now_rows, by_question=False),
        "q_per_paper": questions_per_paper(now_rows),
        "tasks_per_paper": tasks_per_paper(now_rows),
        "qnum_avg_marks": {int(k): v for k, v in a["qnum_avg_marks"].items()},
        "shift": shift, "retired": retired,
        "papers_since_2022": len({r["paper"] for r in every
                                  if r["year"] >= CURRENT_SYLLABUS_FROM}),
        "thresholds": gt, "recent": recent,
        "grade_pct": {g: mean(r["pct"][g] for r in recent) for g in "ABCDE"},
        "grade_raw": grade_raw,
        "y2026": y26, "y2026_mix": mix,
        "recency": recency(every), "repeats": reps, "repeat_count": n_reps,
        "ladder": ladder, "ladder_need": need,
        "twins": variant_twins(paper), "skills": skills,
        "task_map": task_map(task_rows, names),
        "task_strongest": task_strongest(task_map(task_rows, names, top=None),
                                         len({r["paper"] for r in task_rows})),
        "near_dupe_pairs": a["near_duplicate_total_pairs_found"],
        # copy facts (build_report_pdf.py prints these instead of typing them)
        "syllabus_from": CURRENT_SYLLABUS_FROM,
        "first_year": min(r["year"] for r in every),
        "last_year": newest[0], "last_sitting": newest[2],
        "papers_then": n_then, "then_count": then_count,
        "topic_band": topic_bands(now_rows, *USUAL_BAND),
        "size_band": band(list(task_totals(now_rows).values()), *WIDE_BAND),
        "biggest_task": biggest_task(now_rows),
        "er_bullets": er_mentions(paper, r"bullet[ -]point", CURRENT_SYLLABUS_FROM),
        "command_words_page": syllabus_page("Command words"),
        "skills_years": qp_years(paper, skills["sittings"]) if skills else None,
        "task_years": [min(r["year"] for r in task_rows), max(r["year"] for r in task_rows)],
        "threshold_gaps": threshold_gaps(gt),
    }


if __name__ == "__main__":
    for p in "1234":
        s = stats(p)
        print(f"\n===== Paper {p} ({s['kind']}) =====")
        print(f"  {s['papers']} papers used ({s['papers_now']} since 2022), "
              f"{s['questions']} tagged parts, sittings kept {s['sittings'][0]}/{s['sittings'][1]}")
        print("  A %.0f%% (%.0f marks)  C %.0f%%  E %.0f%%" % (
            s["grade_pct"]["A"], s["grade_raw"]["A"], s["grade_pct"]["C"], s["grade_pct"]["E"]))
        print("  --- 2022 onwards ---")
        for t in s["topics"]:
            print("   %-34s %5.1f%%  in %5.1f%% of papers  (%d parts)" % (
                t["name"], t["marks_pct"], t["appears_pct"], t["questions"]))
        print("  top subtopics:", [(x["id"], round(x["pct"])) for x in s["subtopics"][:6]])
        print("  risers:", [(x["name"], round(x["now"] - x["then"], 1)) for x in s["shift"][:3]])
        print("  retired:", s["retired"])
        print("  cmds:", s["cmd_total"], [(c["word"], round(c["pct"])) for c in s["commands"][:5]])
        print("  sizes:", [(x["marks"], round(x["pct"])) for x in s["sizes"][:5]])
