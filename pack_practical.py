"""Write a START_HERE.md into each Chapterwise Practical/<level>_<slug>/ and zip it.

One zip per chapter per level: unzip, pick a year, pick a session, do the questions.
"""
import json, sys, zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_practical_chapters import whole_qnums

ROOT = Path(__file__).parent.parent
SRC = ROOT / "Chapterwise Practical"
OUT = ROOT / "Practical Zips"
LEVEL = {"as": "AS (Paper 2)", "a2": "A Level (Paper 4)"}
MONTH = {"Mar": "February/March", "Jun": "May/June", "Nov": "October/November"}


def start_here(d, groups, shared):
    level, slug = d.name.split("_", 1)
    chapter = groups[0]["chapter"]
    lines = [f"# {chapter} — {LEVEL[level]} practicals, 2020–2025", "",
             f"{len(groups)} exam sessions. Every folder holds only this chapter's questions,",
             "cut from the real paper, with the source files those questions actually use.", "",
             "## How to use it", "",
             "1. Pick a year folder, then a session inside it.",
             "2. Copy `source/` somewhere you can write to, and open the files listed in `notes.md`.",
             "3. Do `QP.pdf` under timed conditions. Mark with `MS.pdf` afterwards.", "",
             "## What's in each session folder", "",
             "| File | What it is |", "| --- | --- |",
             "| `QP.pdf` | Only this chapter's questions, cropped from the original paper. Each is captioned with the paper and question number. |",
             "| `MS.pdf` | The matching mark scheme. |",
             "| `source/` | The Cambridge source files those questions need. Absent when the tasks build from scratch. |",
             "| `notes.md` | Which questions, which files, and what else shipped in that session's archive. |",
             "", "## Sessions", "",
             "| Session | Questions | Source files | Mark scheme | Also covers |",
             "| --- | --- | --- | --- | --- |"]
    for g in sorted(groups, key=lambda g: (2000 + int(g["session"][1:]), g["session"][0])):
        year = 2000 + int(g["session"][1:])
        mon = {"m": "Mar", "s": "Jun", "w": "Nov"}[g["session"][0]]
        leaf = SRC / d.name / str(year) / f"{mon}_{year}"
        nsrc = len(list((leaf / "source").glob("*"))) if (leaf / "source").is_dir() else 0
        flag = ""
        ms = "cropped to this chapter" if (leaf / "MS.pdf").exists() else "—"
        # Cambridge sets some Paper 4 tasks across two chapters at once; the leaf keeps the
        # whole question and says so, and the index has to agree with it.
        also = sorted(shared.get((g["paper"], q), set()) - {g["chapter"]}
                      for q in whole_qnums(g["qnums"]))
        flat = sorted({c for group in also for c in group})
        lines.append(f"| {MONTH[mon]} {year} | {', '.join(whole_qnums(g['qnums']))} | "
                     f"{nsrc or '—'}{flag} | {ms} | {'; '.join(flat) or '—'} |")
    lines += ["", "## Source files", "",
              "Every source file here is the genuine Cambridge confidential-source archive for",
              "that session, downloaded and unpacked as published. Nothing is reconstructed or",
              "substituted.", ""]
    (SRC / d.name / "START_HERE.md").write_text("\n".join(lines))


def main():
    plan = json.load(open(ROOT / "data/practical_plan.json"))
    by_dir = defaultdict(list)
    for g in plan:
        if 2020 <= 2000 + int(g["session"][1:]) <= 2025:
            by_dir[f"{g['level']}_{g['slug']}"].append(g)

    shared = defaultdict(set)
    for g in plan:
        for q in whole_qnums(g["qnums"]):
            shared[(g["paper"], q)].add(g["chapter"])

    # Rewrite only the zips this script makes. Wiping the folder also destroyed zips
    # made elsewhere (as_video_audio_2017-2019.zip), so each zip is overwritten in place.
    OUT.mkdir(exist_ok=True)
    for d in sorted(SRC.iterdir()):
        if not d.is_dir():
            continue
        start_here(d, by_dir[d.name], shared)
        zpath = OUT / f"{d.name}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    z.write(f, Path(d.name) / f.relative_to(d))
        print(f"{zpath.name:28} {zpath.stat().st_size / 1e6:6.1f} MB  "
              f"{len(by_dir[d.name])} sessions")
    print(f"\n-> {OUT}")


if __name__ == "__main__":
    main()
