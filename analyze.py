"""
Data-science pass over all 602 tagged questions: topic/subtopic frequency,
command-word (Describe/Explain/Discuss/Evaluate/...) frequency, marks
distribution, question-number positional patterns, and near-duplicate
detection across sessions. Stdlib only - the dataset is 602 rows, pandas
would be dead weight for this.

Outputs analysis.json for the report/chart-building pass.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from report_stats import analysis_inputs, fingerprint

# Written when everything lived in one flat folder; the vault splits Text/ by paper
# and keeps the JSON under data/, so resolve both from the project root.
PROJECT = Path(__file__).resolve().parent.parent
ROOT = PROJECT / "data"
TEXT_DIR = PROJECT / "Text"
_TEXT_INDEX = {p.stem: p for p in TEXT_DIR.rglob("Paper */*.md")}


def text_of(papercode: str) -> str:
    return _TEXT_INDEX[papercode].read_text()

SEASON_NAME = {"m": "March", "s": "Summer", "w": "Winter"}
SEASON_ORDER = {"m": 0, "s": 1, "w": 2}

# Cambridge's own command-word glossary, as literally used in these MS PDFs
# ("Command word: Evaluate: discuss the importance of..." etc appear verbatim
# in several mark schemes here) plus the other imperative verbs seen opening
# question stems across the corpus.
COMMAND_WORDS = [
    "Analyse", "Compare and contrast", "Compare", "Contrast", "Define",
    "Describe", "Discuss", "Evaluate", "Explain", "Identify", "Justify",
    "State", "Suggest", "Choose", "Complete", "Draw", "Give",
]
# longest-first so "Compare and contrast" wins over bare "Compare"
COMMAND_WORDS.sort(key=len, reverse=True)
# Anchored to sentence/clause boundaries in theory, but real papers break
# that assumption constantly (figure captions like "Fig. 8.2 Describe..."
# have no terminating period before the instruction, code blocks interrupt
# the prose entirely). Since these command words are ALWAYS capitalized
# imperative sentence-openers in Cambridge's own house style - never used
# capitalized mid-sentence for anything else in this corpus - a plain
# case-sensitive whole-word match is actually the more reliable signal.
CMD_RE = re.compile(r"\b(" + "|".join(re.escape(c) for c in COMMAND_WORDS) + r")\b")


def parse_paper(papercode: str):
    m = re.match(r"9626_([msw])(\d{2})_qp_(\d{2})", papercode)
    session, yy, variant = m.groups()
    return session, 2000 + int(yy), variant


def question_stem(papercode: str, qnum: str) -> str:
    text = text_of(papercode)
    pattern = re.compile(
        rf"^## Question {re.escape(qnum)}\b.*?$(.*?)(?=^### Mark scheme)",
        re.M | re.S,
    )
    m = pattern.search(text)
    if not m:
        return ""
    body = m.group(1)
    # strip answer-space dot runs, page furniture, image refs - keep prose only
    lines = []
    for line in body.split("\n"):
        if re.match(r"^\s*\.{5,}", line):
            continue
        if re.match(r"^\s*\d{4}/\d{2}/[A-Z/]+/\d{2}\s*$", line):
            continue
        if line.strip() in ("© UCLES", "[Turn over") or re.match(r"^© UCLES \d{4}$", line.strip()):
            continue
        if line.strip().startswith("!["):
            continue
        if re.match(r"^\s*\d{1,3}\s*$", line):
            continue
        lines.append(line)
    return " ".join(l.strip() for l in lines if l.strip())


def question_marks(papercode: str, qnum: str):
    text = text_of(papercode)
    m = re.search(rf"^## Question {re.escape(qnum)}(?: — (\d+) marks)?", text, re.M)
    return int(m.group(1)) if m and m.group(1) else None


def paper_number(variant: str) -> str:
    """"32" -> Paper 3; "02"/"04" -> Papers 2 and 4 (the practicals lost their
    variant digit from 2019 on, so the leading zero carries the paper number)."""
    return variant[1] if variant[0] == "0" else variant[0]


def find_duplicate_papers(papers: list[str]) -> list[tuple[str, str]]:
    """Cambridge reuses one paper across two variants in the same sitting
    (p3 variant 31 == 33, repeatedly). Rather than hard-code the pairs, compare
    the actual question text: same session+year, identical set of stems -> the
    later variant is a reprint of the earlier one and must not be double-counted."""
    by_session = defaultdict(list)
    for code in papers:
        session, year, variant = parse_paper(code)
        by_session[(session, year)].append(code)
    pairs = []
    for codes in by_session.values():
        fingerprints = {}
        for code in sorted(codes):
            text = text_of(code)
            stems = tuple(sorted(
                re.sub(r"\s+", " ", s)[:200]
                for s in re.findall(r"^## Question .*?$(.*?)(?=^## Question |\Z)", text, re.M | re.S)
            ))
            if not stems:
                continue
            if stems in fingerprints:
                pairs.append((fingerprints[stems], code))
            else:
                fingerprints[stems] = code
    return pairs


def main():
    paper = sys.argv[1] if len(sys.argv) > 1 else "3"
    # report_stats.stats() refuses this file once any of these inputs change.
    inputs_sha256 = fingerprint(analysis_inputs(paper, ROOT))
    taxonomy = json.loads((ROOT / "taxonomy.json").read_text())
    # The tagging manifest keys a unit as "<papercode>:<q><part>" and question_bank.json
    # holds that unit's marks and text, so the bank is the source for both rather than
    # re-parsing the Markdown. Parts are kept separate: 1(a) and 1(b) can sit under
    # different topics and collapsing them to "question 1" is what the earlier version
    # of this script did wrong.
    bank = {f"{r['paper']}:{r['q']}{r['part'] or ''}": r
            for r in json.loads((ROOT / "question_bank.json").read_text())}
    manifest = []
    for f in sorted(ROOT.glob("tagging_manifest_p*.jsonl")):
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            e = json.loads(line)
            papercode = e["id"].split(":")[0]
            if paper_number(parse_paper(papercode)[2]) == paper:
                manifest.append(e)
    if not manifest:
        sys.exit(f"No tagged questions found for Paper {paper}.")

    dup_pairs = find_duplicate_papers(sorted({e["id"].split(":")[0] for e in manifest}))
    dup_of = {b: a for a, b in dup_pairs}  # treat b as a duplicate of a

    rows, missing = [], 0
    for entry in manifest:
        unit = bank.get(entry["id"])
        if unit is None:
            missing += 1
            continue
        papercode = unit["paper"]
        session, year, variant = parse_paper(papercode)
        stem = "\n".join(x for x in (unit["stem"], unit["part_stem"], unit["text"]) if x)
        rows.append({
            "paper": papercode, "q": unit["q"] + (unit["part"] or ""),
            "session": session, "year": year, "variant": variant,
            "marks": unit["marks"],
            "tags": [{"topic": s} for s in entry["topics"]],
            "stem": stem, "commands": CMD_RE.findall(stem),
            "is_dup_of": dup_of.get(papercode),
        })
    if missing:
        print(f"  warning: {missing} tagged units have no entry in question_bank.json")

    # ================= topic / subtopic frequency =================
    topic_count = Counter()
    subtopic_count = Counter()
    topic_marks = defaultdict(int)
    subtopic_marks = defaultdict(int)
    topic_count_unique = Counter()  # excluding duplicate-variant re-asks
    for r in rows:
        is_dup = r["is_dup_of"] is not None
        for tag in r["tags"]:
            sub = tag["topic"]
            top = sub.split(".")[0]
            topic_count[top] += 1
            subtopic_count[sub] += 1
            if r["marks"]:
                topic_marks[top] += r["marks"]
                subtopic_marks[sub] += r["marks"]
            if not is_dup:
                topic_count_unique[top] += 1

    # ================= how many real papers touch each topic/subtopic =================
    # "chance the next paper has this topic" - every one of the 55 actual sittings
    # is an independent draw a candidate might face, so this counts real papers,
    # not deduplicated content (unlike the frequency counts above).
    all_papers = sorted({r["paper"] for r in rows})
    total_papers = len(all_papers)
    papers_with_topic = defaultdict(set)
    papers_with_subtopic = defaultdict(set)
    for r in rows:
        for tag in r["tags"]:
            sub = tag["topic"]
            top = sub.split(".")[0]
            papers_with_topic[top].add(r["paper"])
            papers_with_subtopic[sub].add(r["paper"])
    topic_paper_share = {t: len(ps) / total_papers * 100 for t, ps in papers_with_topic.items()}
    subtopic_paper_share = {s: len(ps) / total_papers * 100 for s, ps in papers_with_subtopic.items()}

    # ================= command word frequency =================
    cmd_count = Counter()
    cmd_by_topic = defaultdict(Counter)
    for r in rows:
        for c in r["commands"]:
            cmd_count[c] += 1
            for tag in r["tags"]:
                cmd_by_topic[tag["topic"].split(".")[0]][c] += 1
    # how many questions have NO detected command word (edge cases / code completion tasks)
    no_command = sum(1 for r in rows if not r["commands"])

    # ================= marks distribution =================
    all_marks = [r["marks"] for r in rows if r["marks"]]
    marks_hist = Counter(all_marks)

    # ================= positional pattern: question number -> topic =================
    qnum_topic = defaultdict(Counter)
    qnum_marks = defaultdict(list)
    # r["q"] is "7" or "7(b)(ii)". Position is a property of the question, so the
    # parts are summed back up before averaging; otherwise "marks at question 1"
    # reports the size of one sub-part and looks absurdly small.
    per_question = defaultdict(int)
    for r in rows:
        head = re.match(r"\d+", r["q"])
        if not head:
            continue
        qn = int(head.group())
        per_question[(r["paper"], qn)] += r["marks"] or 0
        for tag in r["tags"]:
            qnum_topic[qn][tag["topic"].split(".")[0]] += 1
    for (_paper, qn), total in per_question.items():
        if total:
            qnum_marks[qn].append(total)

    # ================= near-duplicate detection (excluding known variant pairs) =================
    # compare unique-content questions pairwise on normalized stem text
    unique_rows = [r for r in rows if r["is_dup_of"] is None and len(r["stem"]) > 30]
    near_dupes = []
    seen_papers_pairs = set()
    # bucket by first 4 words to cut comparisons down
    buckets = defaultdict(list)
    for r in unique_rows:
        words = re.findall(r"[a-zA-Z]+", r["stem"].lower())
        key = " ".join(words[:3])
        buckets[key].append(r)
    for key, bucket in buckets.items():
        if len(bucket) < 2:
            continue
        for i in range(len(bucket)):
            for j in range(i + 1, len(bucket)):
                a, b = bucket[i], bucket[j]
                if a["paper"] == b["paper"]:
                    continue
                ratio = SequenceMatcher(None, a["stem"], b["stem"]).ratio()
                if ratio > 0.55:
                    near_dupes.append({
                        "a": f"{a['paper']} Q{a['q']}", "b": f"{b['paper']} Q{b['q']}",
                        "similarity": round(ratio, 3),
                        "a_stem": a["stem"][:150], "b_stem": b["stem"][:150],
                    })
    near_dupes.sort(key=lambda x: -x["similarity"])

    # ================= sub-sub-topic keyword themes (13.1 New & emerging tech) =================
    THEMES_13_1 = {
        "AI / expert systems / chatbots": ["artificial intelligence", r"\bAI\b", "chatbot", "automated online assistant"],
        "AR / VR": ["augmented reality", "virtual reality"],
        "Robotics": ["robot"],
        "3D printing": ["3D printing", "3D print"],
        "Wearable computing": ["wearable"],
        "Blockchain / cryptocurrency": ["blockchain", "cryptocurrency", "bitcoin", "digital currency", "digital currencies"],
        "IoT": ["internet of things", r"\bIoT\b"],
        "Holographic imaging/storage": ["holographic"],
        "Biometrics": ["biometric"],
        "Computer-assisted translation": ["computer-assisted translation", "computer assisted translation"],
        "Vision enhancement": ["vision enhancement"],
        "Autonomous transport": ["autonomous transport", "autonomous vehicle"],
        "CAD/CAM": ["computer-aided design", "computer aided design", r"\bCAD\b", "computer-aided manufactur", r"\bCAM\b"],
        "QR codes": ["QR code"],
        "Quantum computing/cryptography": ["quantum"],
        "Molecular/4th-gen storage": ["molecular data storage", "4th generation optical", "fourth.{0,15}generation optical"],
    }
    theme_hits = Counter()
    for r in unique_rows:
        for tag in r["tags"]:
            if tag["topic"] != "13.1":
                continue
            for theme, patterns in THEMES_13_1.items():
                if any(re.search(p, r["stem"], re.I) for p in patterns):
                    theme_hits[theme] += 1

    # ================= sub-sub-topics for 14 Communications (already has subtopics, but check wireless tech themes) =================
    THEMES_14_7 = {
        "Wi-Fi": [r"\bwi-?fi\b"],
        "Bluetooth": ["bluetooth"],
        "Infrared": ["infra-?red"],
        "Microwave": ["microwave"],
        "NFC": [r"\bNFC\b", "near field communication"],
        "Radio": [r"\bradio\b"],
    }
    theme_14_7 = Counter()
    for r in unique_rows:
        for tag in r["tags"]:
            if tag["topic"] != "14.7":
                continue
            for theme, patterns in THEMES_14_7.items():
                if any(re.search(p, r["stem"], re.I) for p in patterns):
                    theme_14_7[theme] += 1

    # ================= sub-sub-topics for 21.1 Programming for the web =================
    # 21.1 is the ONLY subtopic under topic 21, so every web-programming question
    # lands in one bucket in the subtopic chart - same problem as 13.1. Breaking
    # it out by JavaScript concept (loops, events, arrays...) the same way.
    THEMES_21_1 = {
        "Loops (for/while)": [r"\bloop", "iterative", r"\bfor\b.{0,10}loop", "while", r"\bdo/while\b"],
        "Events (onclick etc.)": ["onclick", "onload", "onchange", "onmouseover", "onkeydown", "html event", "event handler", "event handling"],
        "Arrays": [r"\barray", r"\.sort\(\)", r"\blist of\b"],
        "Conditionals / comparison": ["if.{0,4}else", "switch", "comparison operator", r"==", "conditional statement", "if statement"],
        "Functions": [r"\bfunction\b"],
        "Output (write/innerHTML/alert)": ["document\\.write", "innerhtml", r"\balert\(", "console\\.log", "prompt\\(", "confirm\\("],
        "Variables / data types": ["variable", "data type", r"\bstring\b", "primitive", r"\bboolean\b"],
        "Errors / exceptions": ["error", "exception", r"\btry\b", r"\bcatch\b", "debug"],
        "Objects / properties": [r"\bobject\b", "property", "properties"],
        "Timing (setTimeout/setInterval)": ["settimeout", "setinterval", "timing event"],
        "Comments in code": [r"\bcomment"],
    }
    theme_21_1 = Counter()
    for r in unique_rows:
        for tag in r["tags"]:
            if tag["topic"] != "21.1":
                continue
            for theme, patterns in THEMES_21_1.items():
                if any(re.search(p, r["stem"], re.I) for p in patterns):
                    theme_21_1[theme] += 1

    # ================= sub-sub-topics for the other single-subtopic topics =================
    # 17, 18 and 20 are also defined by the syllabus as one subtopic each - same
    # situation as 13 and 21, just lower volume. Themed the same way for consistency.
    THEMES_BY_SUBTOPIC = {
        # ---- AS topics 1-11 (Papers 1 and 2). Same trick as the A-Level ones below:
        # several of these subtopics are broad enough that the subtopic chart alone
        # says nothing about WHAT gets asked, so they get keyword themes too.
        "1.3": {
            "Symmetric encryption": ["symmetric"],
            "Asymmetric / public-private key": ["asymmetric", "public key", "private key"],
            "SSL / TLS / HTTPS": [r"\bSSL\b", r"\bTLS\b", "https", "digital certificate"],
            "Encryption keys & key length": ["key length", "encryption key", "bit key"],
            "Caesar / simple ciphers": ["caesar", "cipher"],
            "Hard disk / file encryption": ["encrypt.{0,20}(hard )?disk", "encrypt.{0,15}file"],
        },
        "1.4": {
            "Validation": ["validation", "validate"],
            "Verification": ["verification", "verify", "double entry", "visual check"],
            "Range / limit check": ["range check", "limit check"],
            "Type / character check": ["type check", "character check", "format check"],
            "Length check": ["length check"],
            "Presence check": ["presence check"],
            "Check digit": ["check digit"],
            "Lookup / consistency check": ["look-?up check", "consistency check"],
        },
        "1.5": {
            "Batch processing": ["batch process"],
            "Online / interactive processing": ["online process", "interactive process"],
            "Real-time processing": ["real-?time"],
            "Master / transaction files": ["master file", "transaction file"],
        },
        "2.1": {
            "Mainframes": ["mainframe"],
            "Supercomputers": ["supercomputer"],
            "RAS / fault tolerance": [r"\bRAS\b", "fault toleran", "reliability", "serviceability"],
            "Performance metrics (MIPS/FLOPS)": [r"\bMIPS\b", r"\bFLOPS\b", "performance metric"],
        },
        "2.2": {
            "Compilers / interpreters": ["compiler", "interpreter", "cross compil"],
            "Linkers": ["linker"],
            "Device drivers": ["device driver"],
            "Operating systems": ["operating system"],
        },
        "2.5": {
            "GUI / WIMP": [r"\bGUI\b", "graphical user interface", r"\bWIMP\b"],
            "Command line": ["command line", r"\bCLI\b"],
            "Dialogue / voice interface": ["dialogue interface", "voice", "speech"],
            "Gesture-based": ["gesture"],
            "Form / menu driven": ["form.{0,10}(based|driven)", "menu.{0,10}driven"],
        },
        "3.1": {
            "Sensors": ["sensor"],
            "Data logging": ["data logging", "data logger"],
            "Monitoring in health/weather/traffic": ["patient", "weather", "traffic", "pollution", "burglar"],
        },
        "3.2": {
            "Actuators": ["actuator"],
            "Feedback loops": ["feedback"],
            "Microprocessor control": ["microprocessor", "control system"],
            "Turtle graphics / robotics": ["turtle", "robot"],
        },
        "4.1": {
            "Pseudocode": ["pseudocode", "pseudo-code"],
            "Sequence / selection / iteration": ["sequence", "selection", "iteration", "loop"],
            "Sorting / searching": ["sort", "search"],
        },
        "4.2": {
            "Flowchart symbols": ["symbol", "decision box", "process box", "terminator"],
            "Completing a flowchart": ["complete the flowchart", "draw a flowchart", "complete the diagram"],
        },
        "5.1": {
            "Phishing / pharming / smishing": ["phishing", "pharming", "smishing", "vishing"],
            "Hacking": ["hack"],
            "Identity theft / fraud": ["identity theft", "fraud"],
            "Passwords / authentication": ["password", "authenticat", "two-?factor", "biometric"],
            "Firewalls": ["firewall"],
        },
        "5.2": {
            "Viruses / worms": ["virus", "worm"],
            "Trojans": ["trojan"],
            "Spyware / keyloggers": ["spyware", "key ?logger"],
            "Ransomware": ["ransomware"],
            "Adware": ["adware"],
            "Anti-malware / protection": ["anti-?virus", "anti-?malware", "anti-?spyware"],
        },
        "6.1": {
            "Causes of the divide": ["cause", "reason", "why.{0,20}divide", "income", "poverty", "cost of"],
            "Geography (rural vs urban, country)": ["rural", "urban", "developing countr", "geograph", "remote area"],
            "Age / generation gap": [r"\bage\b", "older people", "elderly", "young"],
            "Education / skills / literacy": ["educat", "skill", "literac", "training"],
            "Disability / accessibility": ["disab", "accessib", "impair"],
            "Effects of the divide": ["effect", "impact", "consequence", "disadvantage"],
            "Ways to reduce it": ["reduce", "narrow", "bridge", "solution", "overcome", "government"],
        },
        "7.1": {
            "Knowledge base": ["knowledge base"],
            "Inference engine": ["inference engine"],
            "Rule base": ["rule base", "rules base"],
            "Explanation system": ["explanation system"],
            "User interface / shell": ["user interface", r"\bshell\b"],
            "Applications (medical, mineral, chess...)": ["diagnos", "mineral", "prospect", "chess", "financial", "route", "car engine"],
        },
        "8.1": {
            "Formulae & cell references": ["formula", "cell reference", "absolute", "relative"],
            "Functions (IF/LOOKUP/COUNT/SUM...)": [r"\bIF\b", "lookup", "vlookup", "hlookup", "countif", "sumif", r"\bSUM\b", "index", "match", "round"],
            "Validation in a sheet": ["validation", "drop.?down", "input message", "error alert"],
            "Formatting & conditional formatting": ["conditional format", "format.{0,15}cell", "currency", "decimal place"],
            "Named ranges": ["named range", "range name"],
            "Protection / hiding": ["protect", "hide", "hidden", "password"],
        },
        "8.2": {
            "Test data (normal/extreme/abnormal)": ["normal data", "extreme data", "abnormal", "erroneous", "boundary"],
            "Test plan / expected results": ["test plan", "expected result", "test table"],
        },
        "8.3": {
            "Sorting & filtering": ["sort", "filter"],
            "Importing / exporting data": ["import", "export", r"\bcsv\b"],
            "What-if / goal seek": ["what.?if", "goal seek", "scenario", "solver"],
            "Macros / automation": ["macro", "automat"],
        },
        "8.4": {
            "Bar / column charts": ["bar chart", "column chart"],
            "Line graphs": ["line graph", "line chart"],
            "Pie charts": ["pie chart"],
            "Scatter / XY": ["scatter", r"\bXY\b"],
            "Chart formatting (axes, labels, legend)": ["axis", "axes", "legend", "data label", "title"],
        },
        "9.1": {
            "Financial models / break-even": ["break.?even", "profit", "cash ?flow", "budget", "loan", "interest"],
            "Simulations (flight, weather, traffic)": ["flight simulat", "weather", "traffic", "queue", "population"],
            "Variables & rules of a model": ["variable", "rule", "assumption"],
            "Advantages / risks of modelling": ["advantage", "disadvantage", "risk", "why.{0,20}model"],
        },
        "10.1": {
            "Tables, fields, records": ["table", "field", "record"],
            "Data types & field properties": ["data type", "field (length|size)", "propert"],
            "Primary / foreign keys": ["primary key", "foreign key", "composite key"],
            "Relationships": ["relationship", "one-to-many", "many-to-many"],
            "Queries": ["quer(y|ies)", "parameter query", "criteria"],
            "Forms & reports": ["\bform\b", "report"],
        },
        "10.2": {
            "1NF": [r"\b1NF\b", "first normal form"],
            "2NF": [r"\b2NF\b", "second normal form"],
            "3NF": [r"\b3NF\b", "third normal form"],
            "Redundancy / anomalies": ["redundan", "anomal", "duplicate data"],
        },
        "10.3": {
            "Data dictionary contents": ["data dictionary", "field name", "validation", "index"],
        },
        "10.4": {
            "File types (serial/sequential/random)": ["serial", "sequential", "random access", "indexed"],
            "Backup & archiving": ["back.?up", "archiv"],
            "File compression": ["compress", "zip"],
        },
        "11.1": {
            "Trimming / splitting clips": ["trim", "split", "crop", "cut"],
            "Transitions": ["transition", "fade", "dissolve", "wipe"],
            "Titles / captions / credits": ["title", "caption", "credit", "subtitle"],
            "Effects & filters": ["effect", "filter", "slow motion", "chroma"],
            "Export / file formats": ["export", "render", r"\bmp4\b", r"\bavi\b", "aspect ratio", "frame rate"],
        },
        "11.2": {
            "Trimming / mixing audio": ["trim", "mix", "cut", "splice"],
            "Fades & volume": ["fade", "volume", "amplif", "normalis"],
            "Noise removal": ["noise", "hiss", "clean"],
            "Export / audio formats": [r"\bmp3\b", r"\bwav\b", "export", "bit ?rate", "sample rate"],
        },
        # ---- A-Level single-subtopic topics (Papers 3 and 4) ----
        "17.1": {
            "Getting data from multiple sources": ["different sources", "data source", "consolidat", "merging",
                                                    r"\.csv file", "each worksheet", "combine", "update the"],
            "Cleaning / transforming data": ["clean", "transform", "splitting data", "discrete field",
                                              "inconsistent", "format of the", "hide all", "joins together",
                                              "examine the data"],
            "Pivot tables": ["pivot table"],
            "Pivot charts": ["pivot chart"],
            "Summarising / aggregating": ["total", "average", "summar", "count of", "by category", "group"],
        },
        "18.1": {
            "Selecting / filtering recipients": ["select", "filter", "sort", "exclud"],
            "Conditional fields (IF/SKIPIF)": ["if.{0,4}then.{0,4}else", "skipif", "skip record", "next record", "conditional field"],
            "Master document & source data": ["master document", "source (data|file)"],
            "Labels / directories": ["label", "directory"],
            "Inserting fields": ["insert.{0,10}field", "merge field"],
        },
        "20.1": {
            "Key frames / tweening": ["key ?frame", "tween", "inbetween"],
            "Frame rate / timing": ["frame rate", "frames per second", r"\bfps\b", "timing"],
            "Cel / stop-motion / traditional": ["cel animation", "stop motion", "flip book", "time lapse"],
            "Morphing": ["morph"],
            "2D / 3D": [r"\b2D\b", r"\b3D\b"],
            "Layers / masks in animation": ["layer", "mask"],
            "Object properties (position, orientation...)": ["orientation", "position", "propert(y|ies)"],
        },
    }
    theme_by_subtopic = {}
    for sub_id, themes in THEMES_BY_SUBTOPIC.items():
        counter = Counter()
        for r in unique_rows:
            for tag in r["tags"]:
                if tag["topic"] != sub_id:
                    continue
                for theme, patterns in themes.items():
                    if any(re.search(p, r["stem"], re.I) for p in patterns):
                        counter[theme] += 1
        theme_by_subtopic[sub_id] = dict(counter.most_common())

    # ================= year-over-year topic trend =================
    year_topic = defaultdict(Counter)
    for r in rows:
        if r["is_dup_of"]:
            continue
        for tag in r["tags"]:
            year_topic[r["year"]][tag["topic"].split(".")[0]] += 1

    result = {
        "total_questions": len(rows),
        "unique_content_questions": len(unique_rows) + sum(1 for r in rows if r["is_dup_of"] is None and len(r["stem"]) <= 30),
        "duplicate_variant_pairs": len(dup_pairs),
        "duplicate_variant_pair_list": [list(pair) for pair in dup_pairs],
        "topic_names": {k: v["name"] for k, v in taxonomy.items()},
        "topic_count_all_instances": dict(topic_count),
        "topic_count_unique_content": dict(topic_count_unique),
        "subtopic_count": dict(subtopic_count),
        "subtopic_names": {s: name for t in taxonomy.values() for s, name in t["subtopics"].items()},
        "topic_marks_total": dict(topic_marks),
        "subtopic_marks_total": dict(subtopic_marks),
        "command_word_count": dict(cmd_count.most_common()),
        "command_word_by_topic": {k: dict(v) for k, v in cmd_by_topic.items()},
        "questions_with_no_detected_command_word": no_command,
        "marks_histogram": dict(sorted(marks_hist.items())),
        "qnum_topic_distribution": {str(k): dict(v) for k, v in sorted(qnum_topic.items())},
        "qnum_avg_marks": {str(k): round(sum(v) / len(v), 1) for k, v in sorted(qnum_marks.items())},
        "qnum_marks_range": {str(k): [min(v), max(v)] for k, v in sorted(qnum_marks.items())},
        "near_duplicates_top20": near_dupes[:20],
        "near_duplicate_total_pairs_found": len(near_dupes),
        "themes_13_1_new_emerging_tech": dict(theme_hits.most_common()),
        "themes_14_7_wireless": dict(theme_14_7.most_common()),
        "themes_21_1_web_programming": dict(theme_21_1.most_common()),
        "themes_by_subtopic": theme_by_subtopic,
        "total_papers": total_papers,
        "topic_paper_share": topic_paper_share,
        "subtopic_paper_share": subtopic_paper_share,
        "year_topic_trend": {str(k): dict(v) for k, v in sorted(year_topic.items())},
    }

    result["paper"] = paper
    result["inputs_sha256"] = inputs_sha256
    (ROOT / f"analysis_p{paper}.json").write_text(json.dumps(result, indent=2))
    print(f"Analyzed {len(rows)} question-tag rows ({len(unique_rows)} unique-content, "
          f"{len(dup_pairs)} exact variant-duplicate pairs).")
    print(f"Found {len(near_dupes)} near-duplicate question pairs across different sessions (similarity > 0.55).")
    print(f"Written to analysis_p{paper}.json")


if __name__ == "__main__":
    main()
