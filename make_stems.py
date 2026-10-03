"""Text/*.md -> one compact stem file per paper type, for the tagging pass.
Strips mark schemes/images; keeps enough question text to classify against the syllabus."""
import re, sys
from pathlib import Path

OUT = Path("stems"); OUT.mkdir(exist_ok=True)
buckets = {"p1": ("11","12","13"), "p2": ("02",), "p3": ("31","32","33"), "p4": ("04",)}

for label, variants in buckets.items():
    lines = []
    for f in sorted(Path("Text").glob("*.md")):
        if f.stem.split("_")[3] not in variants:
            continue
        body = f.read_text(encoding="utf-8")
        body = body.split("## Full mark scheme")[0]
        for chunk in body.split("\n## Question ")[1:]:
            head, _, rest = chunk.partition("\n")
            qnum = head.split(" ")[0]
            text = rest.split("### Mark scheme")[0]
            text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)       # images
            text = re.sub(r"\.{4,}", " ", text)                     # answer-line dots
            text = " ".join(text.split())
            lines.append(f"{f.stem} | Q{qnum} | {text[:420]}")
    (OUT / f"{label}_stems.txt").write_text("\n".join(lines), encoding="utf-8")
    print(label, len(lines), "questions")
