"""Join tagging manifest + question bank + extracted source files into one plan:
which chapter each practical question belongs to, and which source files it names.

Output: data/practical_plan.json
  [{"paper": "9626_s24_qp_02", "session": "s24", "level": "as", "chapter": "10 Database...",
    "slug": "databases", "qnums": ["1", "2(a)"], "files": ["j24customer.csv", ...]}, ...]
"""
import json, re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent.parent
EXTRACTED = ROOT / "SourceFiles/extracted"

# chapter number -> (folder name, zip slug). Only chapters the practical papers touch.
CHAPTERS = {
    "1": ("1 Data processing and information", "data_processing"),
    "8": ("8 Spreadsheets", "spreadsheets"),
    "9": ("9 Modelling", "modelling"),
    "10": ("10 Database and file concepts", "databases"),
    "11": ("11 Video and audio editing", "video_audio"),
    "12": ("12 IT in society", "it_in_society"),
    "17": ("17 Data Analysis and Visualisation", "data_analysis"),
    "18": ("18 Mail merge", "mail_merge"),
    "19": ("19 Graphics creation", "graphics"),
    "20": ("20 Animation", "animation"),
    "21": ("21 Programming for the web", "web_programming"),
}
# Cambridge's own instruction booklet ships in every archive; it is not question data.
ADMIN = re.compile(r"(practical test|conducting cambridge|9626_|^README\.md$)", re.I)
# Chapters whose tasks all chew on the same supplied dataset. A practical paper walks one
# dataset through these in order ("use the file saved at step 6"), so a later task inherits
# what the earlier ones opened. Video/audio is excluded: it needs media, not the CSV next
# door. Graphics, animation and web programming start from a blank canvas.
DATA_CHAPTERS = {"8", "9", "10", "17", "18"}


def bank_index():
    """(paper, qnum) -> text, with the part-less parent kept as a fallback for the
    ~11 manifest sub-parts the bank stores whole."""
    idx, parent = {}, defaultdict(list)
    for x in json.load(open(ROOT / "data/question_bank.json")):
        q, p = x["q"], x["part"]
        body = " ".join(filter(None, [x.get("stem", ""), x.get("part_stem", ""), x.get("text", "")]))
        key = q if p in (None, "None", "") else f"{q}({p})"
        idx[(x["paper"], key)] = body
        parent[(x["paper"], q)].append(body)
    return idx, parent


def source_dir(paper):
    """9626_s24_qp_02 -> SourceFiles/extracted/9626_s24_sf_02.

    The source zips are named _02/_04 in every year, including the ones whose question
    papers use the _21/_41 variant numbering - that mismatch is what hid the 2020-2021
    archives on the first sweep."""
    sess, var = paper.split("_")[1], paper.split("_")[3]
    for v in (var, {"02": "21", "04": "41"}.get(var, var), {"21": "02", "41": "04"}.get(var, var)):
        d = EXTRACTED / f"9626_{sess}_sf_{v}"
        if d.is_dir():
            return d
    return None


def files_named_in(text, names):
    """Source filenames as they appear in question prose.

    Two forms show up: the full name ("j24customer.csv") and the bare stem
    ("Open the French_Clients file"). PDF extraction also breaks names across lines,
    hence the flexible whitespace. Bare stems are matched case-sensitively and only
    when distinctive, so "Sales.ods" isn't claimed by the word "sales" in prose.
    """
    hits = []
    for name in names:
        stem, ext = Path(name).stem, Path(name).suffix.lstrip(".")
        pat = re.escape(stem).replace(r"\ ", r"\s+")
        if re.search(rf"{pat}\s*\.?\s*{re.escape(ext)}\b", text, re.I):
            hits.append(name)
            continue
        distinctive = len(stem) >= 5 and re.search(r"[_\d]|[a-z][A-Z]", stem)
        if distinctive and re.search(rf"(?<![\w.]){pat}(?![\w.])", text):
            hits.append(name)
    return hits


def main():
    idx, parent = bank_index()
    # (paper, chapter_num) -> {"qnums": [...], "files": set()}
    groups = defaultdict(lambda: {"qnums": [], "files": set()})
    for pnum in ("p2", "p4"):
        for line in open(ROOT / f"data/tagging_manifest_{pnum}.jsonl"):
            d = json.loads(line)
            paper, qnum = d["id"].split(":", 1)
            sd = source_dir(paper)
            names = [] if sd is None else [
                f.name for f in sd.iterdir() if f.is_file() and not ADMIN.search(f.name)]
            text = idx.get((paper, qnum)) or " ".join(parent.get((paper, re.match(r"\d+", qnum).group(0)), []))
            hits = files_named_in(text, names)
            for topic in d["topics"]:
                ch = topic.split(".")[0]
                if ch not in CHAPTERS:
                    continue
                g = groups[(paper, ch)]
                g["qnums"].append(qnum)
                g["files"].update(hits)

    # Practical tasks chain forward over one dataset, so a data chapter also gets whatever
    # earlier data-chapter questions in the same paper opened - that is the file the task
    # means by "the spreadsheet you saved at step 6". Ordering is by question number.
    def first_q(g):
        return min((int(re.match(r"\d+", q).group()) for q in g["qnums"]), default=99)

    inherited = set()
    for paper in {p for p, _ in groups}:
        data_groups = sorted(((ch, g) for (p, ch), g in groups.items()
                              if p == paper and ch in DATA_CHAPTERS),
                             key=lambda kv: first_q(kv[1]))
        running = set()
        for ch, g in data_groups:
            if running - g["files"]:
                inherited.add((paper, ch))
            g["files"] = set(g["files"]) | running
            running |= set(g["files"])

    plan = []
    for (paper, ch), g in sorted(groups.items()):
        folder, slug = CHAPTERS[ch]
        plan.append({
            "paper": paper, "session": paper.split("_")[1],
            "level": "as" if paper.endswith(("02", "2", "21")) else "a2",
            "chapter": folder, "slug": slug,
            "qnums": sorted(set(g["qnums"]), key=lambda s: (int(re.match(r"\d+", s).group()), s)),
            "files": sorted(g["files"]),
            "source_dir": str(source_dir(paper) or ""),
            "inherited": (paper, ch) in inherited,
        })
    out = ROOT / "data/practical_plan.json"
    out.write_text(json.dumps(plan, indent=1))
    print(f"{len(plan)} (paper, chapter) groups -> {out}")
    return plan


if __name__ == "__main__":
    main()
