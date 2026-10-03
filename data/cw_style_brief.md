# Brief: rewrite the guide's prose in simple, direct English

Files: /home/user/9626-report/data/cw_sections/<Group>.json. Readers are 16-18 year old students,
many reading English as a second language. Rewrite ONLY these prose fields: "text", "one_line",
"context", "why", "note", "thin_evidence", and the "sentence" fields of worked examples.
NEVER change "quote", "doc", "page", "ref", or a weak example's "answer" (it shows a real kind of
mistake on purpose). Do not add facts, numbers or advice that the field did not already contain,
and do not drop a qualifier that limits a claim ("some", "in 2022-2023", "one report"). The cited
quotes must still support each claim after your rewrite.

## Rules (ASD-STE100 Simplified Technical English, adapted)
1. One idea per sentence. Instructions: 20 words or fewer. Descriptions: 25 or fewer.
2. Active voice. "The examiner gives a mark" not "a mark is given". Address the student as "you".
3. Use the imperative for instructions: "Write full sentences." "Give a reason for each point."
4. Use simple, common words. Use one word for one meaning and keep it (e.g. always "point",
   "reason", "mark scheme", "examiner report"; do not cycle synonyms).
5. No em dashes or en dashes, no semicolons. Use a full stop or a comma.
6. No filler or AI-sounding words: crucial, vital, key (as an adjective), essential, valuable,
   ensure, enhance, highlight, underscore, additionally, furthermore, moreover, in order to,
   it is important to note, not just/not only ... but. No groups of three for rhythm.
7. Plain numbers ("6 of 8 marks"). Dates as "June 2024", papers as "Paper 12".
8. Keep it human: short sentences next to slightly longer ones is fine. No upbeat endings.

## Check
From /home/user/9626-report run, for each of your groups:
  python3 cw_style.py <Group>     (must print 0 failures; reduce passive-voice warnings where a
                                   natural active sentence exists, but leave correct passives
                                   such as "marks are not deducted" inside an explanation of a rule)
  python3 cw_verify.py <Group>    (must stay all verified)
Reply with the final line of each command and 3-5 before/after examples of your biggest changes.
