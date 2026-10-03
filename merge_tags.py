"""
Tagging batch outputs -> data/tagging_manifest_p{1,2,3,4}.jsonl

Validates every line against the question bank and the taxonomy before writing,
so a bad subtopic number or a hallucinated unit id fails here rather than
silently vanishing from the topic files. Also writes a review list of the
low-confidence calls.

usage:
  merge_tags.py <dir-of-agent-jsonl>
      Full rebuild: the manifests become exactly what the directory holds.
  merge_tags.py --onto-manifests <file-or-dir> [...]
      Re-tag pass: start from the current manifests and apply each file on top,
      later file wins. Given a directory, only its retag_*.jsonl files are applied.

Do not run the full rebuild on data/tag_raw. It holds 4 of the original tagging
batches (693 of 2,213 units), so the rebuild would wipe the other 1,520 tags. The
original batch folder no longer exists; the manifests are the record now.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ONTO = "--onto-manifests" in sys.argv[1:]
ARGS = [Path(a) for a in sys.argv[1:] if a != "--onto-manifests"]
if not ARGS:
    sys.exit(__doc__)


def tag_files():
    if not ONTO:
        return sorted(ARGS[0].glob("*.jsonl"))
    out = []
    for a in ARGS:
        out += sorted(a.glob("retag_*.jsonl")) if a.is_dir() else [a]
    return out


def paper_no(papercode: str) -> str:
    v = papercode.split("_")[-1]
    return v[1] if v[0] == "0" else v[0]


def main():
    taxonomy = json.loads((DATA / "taxonomy.json").read_text())
    valid = {s for t in taxonomy.values() for s in t["subtopics"]}
    bank = json.loads((DATA / "question_bank.json").read_text())
    by_id = {f"{u['paper']}:{u['q']}{u['part'] or ''}": u for u in bank}
    taggable = {uid for uid, u in by_id.items() if "dupe_of" not in u}

    seen, problems, retagged = {}, [], []
    if ONTO:
        for p in "1234":
            for line in (DATA / f"tagging_manifest_p{p}.jsonl").read_text().splitlines():
                if line.strip():
                    e = json.loads(line)
                    seen[e["id"]] = e
    for f in tag_files():
        for n, line in enumerate(f.read_text().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"{f.name}:{n} unparseable")
                continue
            uid = e.get("id", "")
            if uid not in by_id:
                problems.append(f"{f.name}:{n} unknown id {uid}")
                continue
            bad = [t for t in e.get("topics", []) if t not in valid]
            if bad:
                problems.append(f"{f.name}:{n} bad subtopic(s) {bad} on {uid}")
                continue
            if uid in seen and not ONTO:
                problems.append(f"{f.name}:{n} duplicate tag for {uid}")
                continue
            if ONTO:
                retagged.append(f"{uid}: {seen.get(uid, {}).get('topics')} -> {e['topics']}")
            seen[uid] = e

    per_paper = defaultdict(list)
    for uid, e in seen.items():
        per_paper[paper_no(by_id[uid]["paper"])].append(e)

    def sort_key(e):
        u = by_id[e["id"]]
        m = re.match(r"9626_([msw])(\d{2})_qp_(\d{2})", u["paper"])
        se, yy, var = m.groups()
        qn = re.match(r"\d+", u["q"])
        return (int(yy), {"m": 0, "s": 1, "w": 2}[se], var,
                int(qn.group()) if qn else 0, u["part"] or "")

    for p, entries in sorted(per_paper.items()):
        entries.sort(key=sort_key)
        out = "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"
        (DATA / f"tagging_manifest_p{p}.jsonl").write_text(out, encoding="utf-8")
        print(f"  data/tagging_manifest_p{p}.jsonl: {len(entries)} units")

    for r in retagged:
        print("  retag", r)
    missing = sorted(taggable - set(seen))
    conf = Counter(e.get("confidence", "?") for e in seen.values())
    print(f"\ntagged {len(seen)} / {len(taggable)} taggable units")
    print(f"confidence: {dict(conf)}")
    print(f"still untagged: {len(missing)}")
    if problems:
        print(f"PROBLEMS: {len(problems)}")
        for p in problems[:20]:
            print("   ", p)

    # review list for the low-confidence calls
    low = [e for e in seen.values() if e.get("confidence") == "low"]
    low.sort(key=sort_key)
    lines = ["# Low-confidence tags to review", "",
             "Mostly older questions testing content dropped from the 2026 syllabus.",
             "", "| Unit | Topic | Reason given |", "| --- | --- | --- |"]
    lines += [f"| `{e['id']}` | {', '.join(e['topics'])} | {e.get('why','')} |" for e in low]
    (DATA / "tagging_review_low_confidence.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote data/tagging_review_low_confidence.md ({len(low)} entries)")

    if missing:
        (DATA / "untagged_units.txt").write_text("\n".join(missing), encoding="utf-8")
        print(f"wrote data/untagged_units.txt ({len(missing)} ids)")


if __name__ == "__main__":
    main()
