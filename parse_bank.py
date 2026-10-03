"""
Text/Paper N/*.md -> data/question_bank.json

One record per *taggable unit*: a whole question when it has no parts, otherwise
one per lettered part ((a), (b), ...), with roman sub-parts kept inside their
letter. Mark scheme blocks are split on the '**Marks: N**' markers the extractor
emits and matched to parts positionally.
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT = ROOT / "Text"

# extraction junk: page footers, watermarks, printer refs, margin text
JUNK = re.compile(
    r"^\s*(?:"
    r"\d{4}/\d{2}/[A-Z](?:/[A-Z])*/\d{2}"          # 9626/32/M/J/17
    r"|©\s*UCLES\s*\d{4}"
    r"|\[?Turn over\]?"
    r"|BLANK PAGE"
    r"|DC\s*\([A-Z]+\)\s*\d+.*"                     # printer reference
    r"|\*\s*\d{6,}\s*\*"                            # barcode
    r"|(?:DO NOT WRITE IN THIS MARGIN\s*)+"
    r"|DFD"
    r"|[^\x00-\x7F\s]{6,}"                          # 2024+ anti-piracy watermark runs
    r"|\d{1,3}"                                     # bare page number
    r"|[,\s\x00-\x1f]+"                             # stray separator bytes
    r"|www\.dynamicpapers\.com"                      # DynamicPapers source watermark
    r")\s*$"
)
BOILERPLATE = (
    "Permission to reproduce items", "reasonable effort has been made by the publisher",
    "copyright acknowledgements", "Local Examinations Syndicate",
    "Cambridge Assessment is the brand name",
)
# a blank answer line: optional list marker ("1.", "(a)", "-") then dot leaders,
# optionally ending in the mark allocation, which we keep
DOTS = re.compile(r"^\s*(?:\d+[.)]|\(\w+\)|[-•])?\s*\.{4,}[\s.]*(\*\*\[\d+\]\*\*)?\s*$")
TRAIL_DOTS = re.compile(r"\s*\.{6,}\s*$")
PART = re.compile(r"^\s*-\s*\(([a-z]|i{1,3}|iv|v|vi{1,3})\)\s*", re.I)
ROMAN = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii"}


def clean(text: str) -> str:
    out = []
    for line in text.split("\n"):
        d = DOTS.match(line)
        if d:
            if d.group(1):
                out.append(d.group(1))       # keep the [4], drop the dot leader
            continue
        if JUNK.match(line) or any(b in line for b in BOILERPLATE):
            continue
        out.append(TRAIL_DOTS.sub("", line))
    t = "\n".join(out)
    t = t.replace("«", "...")           # mojibake ellipsis in pre-2024 mark schemes
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def split_parts(body: str):
    """
    -> (stem, [(label, part_stem, text), ...])

    Leaves are the deepest level present: a lettered part with roman children
    yields one leaf per roman (label 'a(i)'), carrying the letter's own text as
    part_stem. This matches the mark scheme, which emits one block per leaf.
    """
    nodes, cur = [], None          # nodes: [level, label, [lines]]
    stem = []
    for line in body.split("\n"):
        m = PART.match(line)
        if m:
            label = m.group(1).lower()
            level = "roman" if (label in ROMAN and any(n[0] == "letter" for n in nodes)) else "letter"
            nodes.append([level, label, [line[m.end():]]])
            cur = nodes[-1]
        elif cur is not None:
            cur[2].append(line)
        else:
            stem.append(line)

    leaves, i = [], 0
    while i < len(nodes):
        level, label, lines = nodes[i]
        text = "\n".join(lines).strip()
        if level != "letter":                      # stray roman with no parent
            leaves.append((f"({label})", "", text))
            i += 1
            continue
        j = i + 1
        romans = []
        while j < len(nodes) and nodes[j][0] == "roman":
            romans.append(nodes[j])
            j += 1
        if romans:
            for _, rlabel, rlines in romans:
                leaves.append((f"({label})({rlabel})", text, "\n".join(rlines).strip()))
        else:
            leaves.append((f"({label})", "", text))
        i = j
    return "\n".join(stem).strip(), leaves


def split_ms(ms: str):
    """Split a mark scheme on '**Marks: N**' -> [(text, marks), ...]."""
    blocks, buf = [], []
    for line in ms.split("\n"):
        m = re.match(r"^\s*\*\*Marks:\s*(\d+)\*\*\s*$", line)
        if m:
            blocks.append(("\n".join(buf).strip(), int(m.group(1))))
            buf = []
        else:
            buf.append(line)
    tail = "\n".join(buf).strip()
    if tail:
        if blocks:
            # trailing text after the last 'Marks:' marker is the indicative-content
            # appendix CAIE prints under a levels grid - same part, not a new one
            blocks[-1] = (blocks[-1][0] + "\n\n" + tail, blocks[-1][1])
        else:
            blocks.append((tail, None))
    return blocks


MARK = re.compile(r"\*\*\[(\d+)\]\*\*")
MS_MARKS = re.compile(r"^\s*\*\*Marks:\s*\d+\*\*\s*$", re.M)


def qp_marks(text):
    """The marks the question paper prints (**[n]**), summed; None if it prints none.

    Preferred over the mark scheme's 'Marks: N'. On a practical mark scheme that is
    the first table row's 1 mark, not the task's total, and it put half the 2022-23
    IT practicals out by 20 to 70 marks.
    """
    found = MARK.findall(text or "")
    return sum(map(int, found)) if found else None


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def anchor_ms(ms, part_texts):
    """Cut a mark scheme at each part's own wording, which CAIE reprints as the row
    heading. -> one text per part, or None if any part's wording is not found in order.

    Used when the 'Marks: N' blocks do not line up with the parts (a table row the
    extractor split in two, or two rows it merged), which otherwise kept a whole
    30-mark case question as one unit.
    """
    lines = MS_MARKS.sub("", ms).split("\n")
    starts, flat = [], ""
    for ln in lines:
        starts.append(len(flat))
        flat += _norm(ln) + " "
    cuts, pos = [], 0
    for t in part_texts:
        # the mark and a "(line 6)" reference are not reprinted in the heading
        t = re.sub(r"\([^)]*\)", " ", MARK.sub(" ", t))
        key = " ".join(_norm(t).split()[:6])
        at = flat.find(key, pos) if key else -1
        if at < 0:
            return None
        li = max(i for i, s in enumerate(starts) if s <= at)
        if cuts and li <= cuts[-1]:
            return None
        cuts.append(li)
        pos = at + len(key)
    cuts[0] = 0
    return ["\n".join(lines[a:b]).strip() for a, b in zip(cuts, cuts[1:] + [len(lines)])]


def parse_file(path: Path):
    raw = path.read_text(errors="replace")
    papercode = path.stem
    recs = []
    for qm in re.finditer(r"^## Question (\S+?)(?:\s+—\s+(\d+) marks)?\s*$(.*?)(?=^## Question |\Z)",
                          raw, re.M | re.S):
        qnum, qmarks, body = qm.group(1), qm.group(2), qm.group(3)
        body = body.rstrip().removesuffix("---").rstrip()
        qtext, mstext = (body.split("### Mark scheme", 1) + [""])[:2]
        qtext = clean(qtext)
        # drop a leading bare question number line
        qtext = re.sub(rf"^{re.escape(qnum)}(?=\s)\s*", "", qtext)
        ms_blocks = split_ms(clean(mstext))
        stem, parts = split_parts(qtext)
        aligned = bool(parts) and len(parts) == len(ms_blocks)
        leaf_marks = [qp_marks(p[2]) for p in parts]
        # A leaf whose mark went missing means split_parts misread the labels
        # ("(i)" taken for a letter), so the parts are not safe to split on.
        anchored = (None if aligned or not parts or None in leaf_marks
                    or sum(leaf_marks) != qp_marks(qtext)
                    else anchor_ms(clean(mstext), [p[2] for p in parts]))
        if not parts or not (aligned or anchored):
            # Either a genuinely single-part question, or the part/mark-scheme
            # counts disagree - in that case keep the question whole rather than
            # risk pairing a part with someone else's answer.
            recs.append(dict(paper=papercode, q=qnum, part=None,
                             stem="", part_stem="", text=qtext,
                             ms="\n\n".join(b[0] for b in ms_blocks),
                             marks=qp_marks(qtext)
                                   or (ms_blocks[0][1] if len(ms_blocks) == 1 else None)
                                   or (int(qmarks) if qmarks else None),
                             split="whole" if parts else "single"))
        else:
            for i, (label, pstem, ptext) in enumerate(parts):
                blk = ms_blocks[i] if aligned else (anchored[i], None)
                recs.append(dict(paper=papercode, q=qnum, part=label,
                                 stem=stem, part_stem=pstem, text=ptext,
                                 ms=blk[0], marks=leaf_marks[i] or blk[1], split="part"))
        recs[-1]["_nparts"] = len(parts)
        recs[-1]["_nms"] = len(ms_blocks)
    return recs


SESSION_ORDER = {"m": 0, "s": 1, "w": 2}


def unit_id(r):
    return f"{r['paper']}:{r['q']}{r['part'] or ''}"


def paper_no(papercode):
    v = papercode.split("_")[-1]
    return v[1] if v[0] == "0" else v[0]


def dupe_norm(r):
    """Identity of a question ignoring cosmetic/per-variant differences."""
    t = f"{r['stem']} {r['part_stem']} {r['text']}"
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " IMG ", t)     # per-variant image filenames
    t = re.sub(r"9626[_/][A-Za-z0-9_/]+", " ", t)         # paper codes
    t = re.sub(r"\*\*\[\d+\]\*\*", " ", t)              # mark markers
    # keep symbols: '==' vs '!==' are different questions
    t = re.sub(r"[\u2018\u2019]", "'", t)
    t = re.sub(r"[\u201c\u201d]", '"', t)
    t = re.sub(r"[\u2013\u2014]", "-", t)
    t = re.sub(r"\.{4,}", " ", t)
    return re.sub(r"\s+", " ", t.lower()).strip()


def mark_dupes(recs):
    """Group identical questions (same-session cross-variant reprints).

    The first paper in exam order keeps the content; the rest point at it via
    'dupe_of' and are listed on the keeper's 'also_in'.
    """
    def order(r):
        pc = r["paper"]
        m = re.match(r"9626_([msw])(\d{2})_qp_(\d{2})", pc)
        se, yy, var = m.groups()
        return (int(yy), SESSION_ORDER[se], var, r["q"], r["part"] or "")

    groups = {}
    for r in recs:
        key = (paper_no(r["paper"]), dupe_norm(r), r["marks"])
        if not key[1]:
            continue
        groups.setdefault(key, []).append(r)

    ndupe = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=order)
        keeper, rest = members[0], members[1:]
        keeper["also_in"] = [unit_id(x) for x in rest]
        for x in rest:
            x["dupe_of"] = unit_id(keeper)
            ndupe += 1
    return ndupe


def main():
    all_recs, mismatch = [], []
    for f in sorted(TEXT.rglob("Paper */*.md")):
        for r in parse_file(f):
            np, nm = r.pop("_nparts", None), r.pop("_nms", None)
            if np is not None and max(np, 1) != nm:
                mismatch.append((r["paper"], r["q"], np, nm))
            all_recs.append(r)
    ndupe = mark_dupes(all_recs)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "question_bank.json").write_text(
        json.dumps(all_recs, indent=1, ensure_ascii=False), encoding="utf-8")
    import collections
    c = collections.Counter(r["split"] for r in all_recs)
    print(f"units: {len(all_recs)}  (from {len({r['paper'] for r in all_recs})} papers)")
    print(f"  split by part      : {c['part']}")
    print(f"  single-part whole  : {c['single']}")
    print(f"  kept whole (unaligned parts): {c['whole']}")
    print(f"questions: {len({(r['paper'], r['q']) for r in all_recs})}")
    print(f"units with no mark scheme: {sum(1 for r in all_recs if not r['ms'].strip())}")
    print(f"duplicate units folded    : {ndupe}")
    print(f"unique units to tag       : {len(all_recs) - ndupe}")
    return mismatch


if __name__ == "__main__":
    main()
