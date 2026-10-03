"""
question bank + tagging manifests -> "By Topic/Paper N/<topic>.md"

One folder per exam paper, one file per syllabus topic, questions grouped under
their subtopic and ordered by session. Each entry is a header line linking the
question paper and mark scheme PDFs, followed by a question table and an answer
table.

Questions reprinted across variants of the same session (11/12/13, 31/33) appear
once, under a header that links both papers.

Nothing here is 9626-specific beyond data/taxonomy.json and the paper-code
pattern in scripts/parse_bank.py, so a new subject only needs those two changed.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

from format_md import to_cell

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "By Topic"

SEASON_LETTER = {"m": "M", "s": "S", "w": "W"}
SEASON_ORDER = {"m": 0, "s": 1, "w": 2}
PAPER_CODE = re.compile(r"(?P<syl>\d{4})_(?P<season>[msw])(?P<yy>\d{2})_qp_(?P<variant>\d{2})")


def parse_code(papercode: str) -> dict:
    m = PAPER_CODE.match(papercode)
    if not m:
        raise ValueError(f"unrecognised paper code: {papercode}")
    d = m.groupdict()
    d["year"] = 2000 + int(d["yy"])
    # "32" -> paper 3 variant 2; "02"/"04" -> single-variant papers 2 and 4
    d["paper"] = d["variant"][1] if d["variant"][0] == "0" else d["variant"][0]
    return d


def session_key(papercode: str):
    d = parse_code(papercode)
    return (d["year"], SEASON_ORDER[d["season"]], d["variant"])


def qnum_key(q: str, part: str | None):
    n = re.match(r"\d+", q)
    return (int(n.group()) if n else 0, q, part or "")


def pdf_links(papercode: str, label_suffix: str = "") -> str:
    """Wikilinks to the question paper and mark scheme for a paper code."""
    ms = papercode.replace("_qp_", "_ms_")
    q = f"[[{papercode}.pdf|Question{label_suffix}]]"
    a = f"[[{ms}.pdf|Answer{label_suffix}]]"
    return f"{q} | {a}"


def entry_header(units: list[dict]) -> str:
    """
    '#### P 32 | M 2017 | [[..|Question]] | [[..|Answer]]'

    When the same question was reprinted in another variant of the same session,
    both papers are named and both sets of PDFs are linked.
    """
    first = units[0]
    d = parse_code(first["paper"])
    variants = " + ".join(parse_code(u["paper"])["variant"] for u in units)
    when = f"{SEASON_LETTER[d['season']]} {d['year']}"
    if len(units) == 1:
        links = pdf_links(first["paper"])
    else:
        links = " | ".join(
            pdf_links(u["paper"], f" P{parse_code(u['paper'])['variant']}") for u in units
        )
    return f"#### P {variants} | {when} | {links}"


def qlabel(unit: dict) -> str:
    return f"{unit['q']}{unit['part'] or ''}"


def fix_images(cell: str) -> str:
    # Text/Paper N/*.md points at '../images/'; these files sit in By Topic/Paper N/
    return cell.replace("](../images/", "](../../Text/images/")


def question_cell(unit: dict) -> str:
    bits = [b for b in (unit.get("stem"), unit.get("part_stem"), unit["text"]) if b and b.strip()]
    return fix_images(to_cell("\n".join(bits), lead_in=False))


def render_entry(units: list[dict]) -> list[str]:
    """One question (plus any variant reprints) as header + two tables."""
    primary = units[0]
    nos = " / ".join(qlabel(u) for u in units)
    marks = primary["marks"] if primary["marks"] is not None else ""
    q_cell = question_cell(primary)
    a_cell = fix_images(to_cell(primary["ms"])) if primary["ms"].strip() else \
        "*Mark scheme is a diagram — see the linked PDF.*"
    return [
        entry_header(units),
        "",
        "| No. | Question | Marks |",
        "| --- | -------- | ----- |",
        f"| {nos} | {q_cell} | {marks} |",
        "",
        "| Question | Answer | Marks |",
        "| -------- | ------ | ----- |",
        f"| {nos} | {a_cell} | {marks} |",
        "",
        "---",
        "",
    ]


def safe_name(name: str) -> str:
    return name.replace("/", "-").replace(":", "-")


def load_tags() -> dict[str, list[str]]:
    """unit id -> [subtopic, ...] from every data/tagging_manifest_*.jsonl."""
    tags: dict[str, list[str]] = {}
    for f in sorted(DATA.glob("tagging_manifest_*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            tags[e["id"]] = e["topics"]
    return tags


def main():
    taxonomy = json.loads((DATA / "taxonomy.json").read_text())
    bank = json.loads((DATA / "question_bank.json").read_text())
    tags = load_tags()

    by_id = {f"{u['paper']}:{u['q']}{u['part'] or ''}": u for u in bank}

    # paper -> subtopic -> [ [unit, ...reprints], ... ]
    buckets: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    untagged = []
    for uid, unit in by_id.items():
        if "dupe_of" in unit:
            continue                                    # rendered with its keeper
        topics = tags.get(uid)
        if not topics:
            untagged.append(uid)
            continue
        group = [unit] + [by_id[o] for o in unit.get("also_in", []) if o in by_id]
        paper = parse_code(unit["paper"])["paper"]
        for sub in topics:
            buckets[paper][sub].append(group)

    if OUT.exists():
        for f in OUT.rglob("*.md"):
            f.unlink()

    written = entries = 0
    for paper in sorted(buckets):
        pdir = OUT / f"Paper {paper}"
        pdir.mkdir(parents=True, exist_ok=True)
        for tnum in sorted(taxonomy, key=int):
            topic = taxonomy[tnum]
            lines, has_content = [f"# {tnum} {topic['name']} — Paper {paper}", ""], False
            for sub, sub_name in topic["subtopics"].items():
                groups = buckets[paper].get(sub)
                if not groups:
                    continue
                has_content = True
                groups.sort(key=lambda g: (session_key(g[0]["paper"]),
                                           qnum_key(g[0]["q"], g[0]["part"])))
                lines += [f"## {sub} {sub_name}", ""]
                for g in groups:
                    lines += render_entry(g)
                    entries += 1
            if has_content:
                (pdir / f"{safe_name(tnum)} {safe_name(topic['name'])}.md").write_text(
                    "\n".join(lines), encoding="utf-8")
                written += 1

    print(f"wrote {written} topic files across {len(buckets)} paper folders")
    print(f"entries rendered: {entries}")
    if untagged:
        print(f"UNTAGGED units skipped: {len(untagged)} (e.g. {untagged[:5]})")


if __name__ == "__main__":
    main()
