"""Style check for the student-facing prose in data/cw_sections/*.json.

Writing rules (after ASD-STE100 Simplified Technical English, and the usual signs of
machine-written text). Quotations are Cambridge's own words and are never checked.
  - at most 20 words in an instruction, 25 in a description
  - no em or en dashes; no semicolons
  - no words from the AI-tell list; no "not just/not only ... but"
  - flag likely passive voice ("is/are/was/were/be/been + -ed/-en") for a second look
Exit status is the number of hard failures; passive voice is a warning only.

    python3 cw_style.py            # all sections
    python3 cw_style.py Explain    # one
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROSE = {"meaning", "intro", "text", "one_line", "context", "why", "note", "thin_evidence", "sentence"}
TELLS = r"\b(crucial|vital|pivotal|key to|delve|enhance[sd]?|foster|showcase|testament|underscore|highlight(?:s|ing)?|" \
        r"landscape|robust|seamless|leverage|utili[sz]e|additionally|furthermore|moreover|ensure[sd]?|ensuring|" \
        r"in order to|it is important to note|it's worth noting|navigate|journey|realm|tapestry|valuable|essential)\b"
PASSIVE = r"\b(is|are|was|were|be|been|being)\s+(\w+ly\s+)?(\w+ed|given|written|shown|known|seen|taken|made|done|marked|set|put|kept|held|told|paid)\b"
IRREG = {"need", "used", "based", "called", "allowed", "required", "expected", "asked", "capped", "linked", "labelled", "credited", "awarded", "printed", "accepted", "rejected", "tagged", "worth"}

def sentences(t):
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9'\"(])", t.strip()) if s]

def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if k in PROSE and isinstance(v, str): yield path + "." + k, v
            elif k not in ("quote", "doc", "page", "ref", "answer"): yield from walk(v, path + "." + k)
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, f"{path}[{i}]")

def check(name, data):
    hard = warn = 0
    for path, t in walk(data):
        probs = []
        if re.search(r"[—–]", t): probs.append("dash")
        if ";" in t: probs.append("semicolon")
        m = re.search(TELLS, t, re.I)
        if m: probs.append(f"word '{m.group(0)}'")
        if re.search(r"\bnot (just|only|merely)\b", t, re.I): probs.append("not-just")
        for s in sentences(t):
            n = len(re.findall(r"[A-Za-z0-9'’]+", s))
            if n > 25: probs.append(f"{n}-word sentence")
        for p in probs:
            hard += 1; print(f"FAIL {name}{path}: {p}: {t[:140]!r}")
        for m in re.finditer(PASSIVE, t, re.I):
            if m.group(3).lower() in IRREG: continue
            warn += 1; print(f"warn {name}{path}: passive? '{m.group(0)}'")
    return hard, warn

def main(only=None):
    H = W = 0
    for f in sorted((ROOT / "data" / "cw_sections").glob("*.json")):
        if only and f.stem != only: continue
        h, w = check(f.stem, json.loads(f.read_text())); H += h; W += w
    print(f"{H} failures, {W} passive-voice warnings")
    sys.exit(min(H, 255))

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
