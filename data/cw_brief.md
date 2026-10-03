# Brief: drafting one section of the 9626 command-words report

Audience: AS/A Level IT (9626) students, Papers 1 and 3, aged 16-18, many writing in a second
language. Their teacher will hand this out. Students have been told myths (e.g. "write everything
in bullet points"), so every rule must come from Cambridge's own documents, never from
general exam folklore or your own knowledge.

## Sources (all already extracted; do not use the internet)
- Your evidence pack: /home/user/9626-report/data/cw_packs/<Group>.md
- Full page text of every examiner report (ER), mark scheme (MS), question paper (QP), the
  syllabus and the learner guide: /home/user/9626-report/data/cw_pages.jsonl
  (one JSON object per page: doc, kind, page, text). Search it with grep or python.
- Per-part records with command word / marks / MS / ER: /home/user/9626-report/data/cw_parts.json
- Document ids look like 9626_s24_er (June 2024 examiner report), 9626_w23_ms_13 (Nov 2023
  mark scheme, paper 13), 9626_m25_qp_12, 9626_syllabus_2025-2027, 9626_learner_guide.
  Sessions: m = Feb/March, s = May/June, w = Oct/Nov.

## The hard rule
Every claim cites at least one source with a VERBATIM quote (copy it exactly from
cw_pages.jsonl; keep each quote inside one page, 6-60 words, no ellipses inside a quote).
If you cannot find a quote that supports a claim, drop the claim. Do not paraphrase inside
"quote". Do not attribute to the ER something that is only in the MS, or vice versa.
Run `python3 /home/user/9626-report/cw_verify.py <Group>` from /home/user/9626-report until it
prints all quotes verified (it writes the page numbers in for you; you do not need to supply
pages). Prefer evidence from 2022 onward (current syllabus); older evidence is allowed when it
says something the newer documents do not, and the text must not imply it is recent.

## What to find out for each command word
1. The syllabus definition (9626_syllabus_2025-2027, page 66) - quote it.
2. How marks are actually given: look across MANY mark schemes for the pattern (one mark per
   point? point + expansion "(1st)" then "(1)"? "MAX n" per side? a mark for a conclusion or
   an opinion? a mark for a definition first?). State the pattern only if you saw it in several
   mark schemes, and cite two or three.
3. What the examiners say goes wrong: the ER comments on these questions. Cite them.
4. Format: what the ERs say about bullets / tables / sentences / paragraphs for this word.
5. Traps: answering a different command word, ignoring the scenario, repeating the question,
   one-sided answers, vague words ("cheaper", "faster", "easier") - only where an ER says so.
6. One or two worked examples from 2022 onward: a real question (quote its text from the QP),
   then a STRONG answer that you write by combining mark-scheme points into full sentences for
   the exact number of marks available, with each sentence tied to the MS point it earns. If an
   ER describes what weak answers did, add a WEAK answer that shows that failure, and say which
   ER comment it illustrates. Never present your own answer as a real candidate's.

## Output: /home/user/9626-report/data/cw_sections/<Group>.json
{
 "group": "<Group>",
 "words": [{"word": "Explain", "syllabus": {"doc": "9626_syllabus_2025-2027", "quote": "..."}}],
 "one_line": "plain-English one-sentence instruction a student can memorise",
 "points": [
   {"kind": "marks" | "mistake" | "format" | "tip",
    "text": "student-facing statement, plain English, 1-3 short sentences",
    "cites": [{"doc": "...", "ref": "Q4(b)" or "General comments", "quote": "..."}]}
 ],
 "examples": [
   {"doc": "9626_s24_qp_12", "ref": "Q1(b)(ii)", "marks": 3,
    "question": {"doc": "9626_s24_qp_12", "quote": "<verbatim question text>"},
    "context": "one sentence of scenario if the question needs it (your words, optional)",
    "strong": [{"sentence": "...", "earns": {"doc": "9626_s24_ms_12", "quote": "<MS point>"}}],
    "weak": {"answer": "...", "marks_likely": "1 of 3", "why": "...",
             "basis": {"doc": "9626_s24_er", "quote": "..."}} or null,
    "note": "what to learn from this, one or two sentences"}
 ],
 "thin_evidence": "say here if the word is rare and the advice rests on few questions"
}
Aim for 5-10 points per word (fewer for rare words). Quality over volume: a point a teacher
could check in thirty seconds against the cited page.

## Style for the "text" fields
Short sentences. Plain words. Talk to the student ("you"). No hype, no "crucial", "vital",
"key to success". Do not start with "Remember". Use numbers from the evidence ("8 of the 25
Evaluate questions...") only if you counted them yourself from cw_parts.json and say how.
