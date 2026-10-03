// node cw_pdf.js in.html out.pdf - print an HTML file to A4 PDF with page numbers.
const { chromium } = require('playwright');
(async () => {
  const [inp, out] = process.argv.slice(2);
  const b = await chromium.launch();
  const p = await b.newPage();
  await p.goto('file://' + require('path').resolve(inp), { waitUntil: 'load' });
  await p.pdf({ path: out, format: 'A4', printBackground: true, displayHeaderFooter: true,
    headerTemplate: '<span></span>',
    footerTemplate: '<div style="font:10.5px Helvetica,Arial,sans-serif;color:#888;width:100%;padding:0 56px;display:flex;justify-content:space-between"><span>9626 Information Technology · Command words</span><span class="pageNumber"></span></div>',
    margin: { top: '48px', bottom: '56px', left: '0', right: '0' } });
  await b.close();
})();
