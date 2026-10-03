# Brief: last style pass on the section text

Files: /home/user/9626-report/data/cw_sections/<Group>.json. The teacher reviewed the guide. Do
these five things and nothing else. Do not change any number. Never edit "quote" text (you may
remove a whole citation object), "doc", "page", or a weak example's "answer".

1. Quote rhythm. Right now nearly every point has exactly two quotes. Change that:
   - Most points keep ONE quotation: the one that supports the claim most directly.
   - Keep TWO only where the point makes two separate claims that each need support (a count
     and a rule, or an examiner report and a mark scheme that say different things).
   - A point may have NO quotation only if it is a plain instruction that follows from the
     point just before it (e.g. "Give each point its own sentence."), or it only restates the
     syllabus definition already printed under the heading. Use "cites": [] for these. Any
     point that states a fact about marking, examiners or counts keeps at least one quote.
2. Format points. The opening section of the guide already covers "write in full sentences,
   not bullets or tables" in full. In each command-word section, delete points (kind "format"
   or headed like "Write in full sentences" / "Use paragraphs") that only repeat that. KEEP a
   format point only where the advice differs for this word: Compare (write each point as a
   comparison, joined with "whereas"; tables of points), pseudocode and flowchart layout, and
   short-answer words where one word is enough. If a whole heading group becomes empty, it
   disappears; do not invent a replacement.
3. Worked examples: delete every "note" field (set it to "" or remove the key).
4. Rhythm in commentary ("text", "why", "thin_evidence", "context"; NOT the full-mark answer
   "sentence" fields, which model the linking words on purpose): vary sentence length on purpose
   (some under 10 words, some 15 to 25). Cut the chains of "so", "because", "which means" where
   two short sentences or a plain statement read better. Do not merge into sentences over 25
   words.
5. Keep everything else: claims, counts, headings (rename a heading only if its group changed),
   the plain-English rules (no dashes, semicolons, AI vocabulary, contrast-reframes like "X is not
   Y", unnamed "we").

Check from /home/user/9626-report: `python3 cw_style.py <Group>` (0 failures),
`python3 cw_verify.py <Group>` (all verified). Do not run cw_build_report.py (another agent may
be mid-edit). Reply with, per file: points before/after, quotes before/after, format points
removed, and two before/after rhythm examples.
