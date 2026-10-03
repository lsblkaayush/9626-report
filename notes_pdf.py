"""Notes/AS Theory (Short)/*.md -> Notes/AS Theory (Short) PDF/*.pdf, A4.

Same route as the market-analysis report: markdown -> HTML -> Chromium print (Playwright).
Black and grey only. Run with the Playwright venv:
    ~/Downloads/saves/venv/bin/python scripts/notes_pdf.py [chapter.md ...] [--pngs]

Every build is checked twice before it is kept:
  - layout: no table, code block or line wider than the page (Chromium would clip it)
  - text:   every word of the rendered notes appears in the PDF text, same number of times
"""
import collections
import html
import re
import subprocess
import sys
from pathlib import Path

from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "Notes" / "AS Theory (Short)"
OUT = ROOT / "Notes" / "AS Theory (Short) PDF"

PAGE_W, PAGE_H = 210, 297  # A4, mm
MARGIN_X = 20  # mm, left and right

CSS = """
:root { --ink: #16191f; --ink2: #3c4048; --muted: #6b7079; --rule: #d9dbe0; --wash: #f3f4f6;
  --sans: 'Noto Sans', sans-serif; --serif: 'Noto Serif', serif; --mono: 'Noto Sans Mono', 'DejaVu Sans Mono', monospace; }
@page { size: %(w)smm %(h)smm; margin: 22mm 20mm 20mm 20mm;
  @top-left { content: "%(title)s"; font: 8pt var(--sans); color: var(--muted); vertical-align: bottom; padding-bottom: 5mm; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 8.5pt var(--sans); color: var(--ink2); vertical-align: top; padding-top: 5mm; }
}
@page :first { @top-left { content: none; } }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; color: var(--ink); font: 10.5pt/1.6 var(--sans); orphans: 2; widows: 2;
       overflow-wrap: break-word; hyphens: manual; }
p { margin: 0 0 6pt; }
strong { font-weight: 700; }
em { font-style: italic; }
h1 { font: 700 26pt/1.12 var(--serif); margin: 0 0 16pt; letter-spacing: -0.01em; }
h2 { font: 700 17pt/1.22 var(--serif); margin: 24pt 0 10pt; padding-top: 10pt; border-top: 1.4pt solid var(--ink); }
h3 { font: 700 11.5pt/1.3 var(--sans); margin: 15pt 0 5pt; }
h4 { font: 700 10.5pt/1.3 var(--sans); margin: 11pt 0 4pt; color: var(--ink2); }
h1, h2, h3, h4 { break-after: avoid; break-inside: avoid; }
p:has(+ ul), p:has(+ ol), p:has(+ table), p:has(+ pre) { break-after: avoid; }
ul, ol { margin: 0 0 7pt; padding-left: 13pt; }
li { margin: 0 0 2.5pt; padding-left: 1pt; }
li > ul, li > ol { margin: 2.5pt 0 2pt; }
li::marker { color: var(--ink2); }
code { font-family: var(--mono); font-size: 9.2pt; background: var(--wash); padding: 0 2pt; border-radius: 2pt; }
pre { font-family: var(--mono); font-size: 9.2pt; line-height: 1.4; background: var(--wash); border-left: 2pt solid var(--rule);
      padding: 5pt 6pt; margin: 4pt 0 8pt; white-space: pre; break-inside: avoid; }
pre.wrap { white-space: pre-wrap; overflow-wrap: anywhere; }
pre code { background: none; padding: 0; font-size: inherit; }
table { width: 100%%; border-collapse: collapse; margin: 6pt 0 12pt; font-size: 9.8pt; line-height: 1.45; table-layout: auto; }
thead { display: table-header-group; }
th { font-weight: 700; text-align: left; vertical-align: bottom; padding: 0 8pt 4pt 0; border-bottom: 1.1pt solid var(--ink); }
td { vertical-align: top; padding: 5pt 8pt 5pt 0; border-bottom: 0.6pt solid var(--rule); overflow-wrap: break-word; }

th:last-child, td:last-child { padding-right: 0; }
tr { break-inside: avoid; }
hr { border: 0; border-top: 0.6pt solid var(--rule); margin: 8pt 0; }
hr:has(+ h2) { display: none; }
.prio { display: inline-block; font: 600 7.6pt/1.35 var(--sans); color: var(--ink2); border: 0.8pt solid var(--ink2);
        border-radius: 3pt; padding: 1pt 5pt; margin: 0 0 7pt; }
.prio b { font-weight: 800; color: var(--ink); }
.tip { border-left: 2.4pt solid var(--ink); background: var(--wash); padding: 4pt 6pt; margin: 4pt 0 8pt; break-inside: avoid; }
.tip .lab { font-weight: 800; }
.toc { margin: 0 0 6pt; padding: 6pt 0 2pt; border-top: 0.6pt solid var(--rule); border-bottom: 0.6pt solid var(--rule); }
.toc .lab { font: 700 7.6pt/1.3 var(--sans); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-bottom: 3pt; }
.toc ol { list-style: none; padding: 0; margin: 0 0 4pt; }
.toc li { margin: 0 0 2pt; font-size: 9.5pt; }
.toc a { color: var(--ink); text-decoration: none; }
.toc .t { font: 600 7pt var(--sans); color: var(--muted); margin-left: 4pt; }
a { color: var(--ink); }
/* wide tables (3+ columns, long cells) read as stacked cards on a phone */
table.stack, table.stack tbody, table.stack tr, table.stack td { display: block; width: 100%%; }
table.stack thead { display: none; }
table.stack tr { padding: 5pt 0 5pt; border-bottom: 0.6pt solid var(--rule); break-inside: auto; }
table.stack tr:first-child { border-top: 1.1pt solid var(--ink); }
table.stack td { border: 0; padding: 1pt 0 2pt; font-size: 9.5pt; }
table.stack td:first-child { font-weight: 700; font-size: 10pt; padding-bottom: 2pt; break-after: avoid; }
table.stack td:not(:first-child)::before { content: attr(data-h) ": "; font-weight: 700; color: var(--ink2); }
"""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def stack_table(m):
    """3+ column tables with long cells -> stacked cards; each cell keeps its column name."""
    t = m.group(0)
    heads = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", t, flags=re.S)]
    cells = re.findall(r"<td[^>]*>(.*?)</td>", t, flags=re.S)
    longest = max((len(re.sub(r"<[^>]+>", "", c)) for c in cells), default=0)
    if len(heads) < 3 or longest <= 60:
        return t
    def td(row):
        i = iter(heads)
        return re.sub(r"<td([^>]*)>", lambda c: f'<td{c.group(1)} data-h="{html.escape(next(i, ""), quote=True)}">', row)
    return re.sub(r"<tr>(.*?)</tr>", lambda r: "<tr>" + td(r.group(1)) + "</tr>", t.replace("<table>", '<table class="stack">'), flags=re.S)


def to_html(md_text):
    md = MarkdownIt("commonmark", {"html": False, "typographer": False}).enable("table")
    body = md.render(md_text)
    # Priority labels -> small tag. "*Priority: HIGH. About 3 marks ...*"
    body = re.sub(r"<p><em>Priority: (HIGH|MEDIUM|LOW)\.\s*(.*?)</em></p>",
                  lambda m: f'<p class="prio">Priority: <b>{m.group(1)}</b> · {m.group(2)}</p>', body)
    # Exam tips -> ruled box
    body = re.sub(r"<p>(?:<strong>)?Exam tip:?(?:</strong>)?:?\s*(.*?)</p>",
                  r'<div class="tip"><span class="lab">Exam tip:</span> \1</div>', body, flags=re.S)
    # long inline formulas wrap after commas, not mid-word
    body = re.sub(r"(?<!<pre>)<code>(.*?)</code>", lambda m: "<code>" + m.group(1).replace(",", ",<wbr>") + "</code>", body, flags=re.S)
    # ids on h2 for the contents list and PDF bookmarks
    heads = []

    def h2(m):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        hid = slug(text)
        heads.append((hid, html.unescape(text)))
        return f'<h2 id="{hid}">{m.group(1)}</h2>'
    body = re.sub(r"<h2>(.*?)</h2>", h2, body, flags=re.S)
    return body, heads


def toc(heads, md_text):
    tiers = {}
    for m in re.finditer(r"^##\s+(.+?)\n\s*\n\*Priority: (HIGH|MEDIUM|LOW)", md_text, flags=re.M):
        tiers[slug(m.group(1))] = m.group(2)
    items = "".join(f'<li><a href="#{h}">{html.escape(t)}</a>'
                    f'{f" <span class=t>{tiers[h]}</span>" if h in tiers else ""}</li>' for h, t in heads)
    return f'<nav class="toc"><div class="lab">In this chapter</div><ol>{items}</ol></nav>' if heads else ""


def build_doc(md_path):
    md_text = md_path.read_text()
    body, heads = to_html(md_text)
    title = re.sub(r"^#\s+", "", md_text.splitlines()[0]).strip()
    # contents list goes straight after the h1 and the block that follows it (the "Most marks come from" list)
    css = CSS % {"w": PAGE_W, "h": PAGE_H, "title": title.replace('"', "'")}
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f'<style>{css}</style></head><body>{body}</body></html>'), title


def words(s):
    return collections.Counter(re.findall(r"[A-Za-z0-9]+", s))


def check_layout(page):
    """Elements wider than the printable column. Run in print media at the page's content width."""
    return page.evaluate("""() => {
        const out = [];
        const W = document.body.clientWidth + 0.5;
        for (const el of document.querySelectorAll('table, pre, p, li, h1, h2, h3, h4, .tip, code')) {
            const r = el.getBoundingClientRect();
            if (r.width > W || el.scrollWidth > el.clientWidth + 1)
                out.push(el.tagName + ': ' + el.innerText.slice(0, 70).replace(/\\s+/g, ' '));
        }
        return out;
    }""")


def build(browser, md_path, pngs=False):
    doc, title = build_doc(md_path)
    OUT.mkdir(exist_ok=True)
    pdf = OUT / (md_path.stem + ".pdf")
    tmp = OUT / ".build.html"
    tmp.write_text(doc)
    page = browser.new_page(viewport={"width": round((PAGE_W - 2 * MARGIN_X) / 25.4 * 96), "height": 1000})
    page.emulate_media(media="print")
    page.goto(tmp.as_uri())
    page.evaluate("document.fonts.ready")
    # code keeps its line layout (ASCII flowcharts): shrink a wide block to fit; wrap only if it would go below 5.5pt
    page.evaluate("""() => { for (const pre of document.querySelectorAll('pre')) {
        const avail = pre.clientWidth - 12, need = pre.scrollWidth - 12;
        if (need <= avail) continue;
        const size = 9.2 * avail / need;
        if (size >= 5.5) pre.style.fontSize = (size - 0.05).toFixed(2) + 'pt'; else pre.classList.add('wrap');
    } }""")
    wide = check_layout(page)
    rendered = page.evaluate("""() => { const c = document.body.cloneNode(true);
        c.querySelectorAll('pre').forEach(e => e.replaceWith(' ')); document.body.after(c);
        const t = c.innerText; c.remove(); return t; }""")
    codes = page.evaluate("[...document.querySelectorAll('pre')].map(e => e.innerText)")
    page.pdf(path=str(pdf), prefer_css_page_size=True, print_background=True, outline=True, tagged=True)
    page.close()
    tmp.unlink()

    text = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout
    want, got = words(rendered), words(text)
    missing = {w: n - got[w] for w, n in want.items() if got[w] < n}
    # code blocks keep their lines (shrunk, never wrapped), so each line must appear whole in the layout text
    flat = re.sub(r"[\s-]+", "", text)
    for c in codes:
        for line in c.splitlines():
            if re.sub(r"[\s-]+", "", line) not in flat:
                missing["CODE LINE: " + line.strip()[:60]] = 1
    pages = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout).group(1))
    if pngs:
        d = OUT / ".png" / md_path.stem
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.png"):
            f.unlink()
        subprocess.run(["pdftoppm", "-r", "110", "-png", str(pdf), str(d / "p")], check=True)
    return pdf, pages, wide, missing


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = [SRC / a for a in args] if args else sorted(p for p in SRC.glob("*.md"))
    ok = True
    with sync_playwright() as p:
        b = p.chromium.launch()
        for f in files:
            pdf, pages, wide, missing = build(b, f, "--pngs" in sys.argv)
            status = "OK" if not wide and not missing else "CHECK"
            ok &= status == "OK"
            print(f"{status}  {pdf.name}: {pages} pages")
            for w in wide:
                print("   too wide:", w)
            if missing:
                print("   words missing from PDF:", dict(list(missing.items())[:30]))
        b.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
