// Review-deck generator. Called by build_decks.py with a JSON payload path:
//   node deck_case_slides.js payload.json out.pptx
// Payload: { title, subtitle, criteria_version, sections:
//   [{ heading, color, scans: [{sub, ses, status, verify, note, metrics:{...},
//                                figures:{carpet, coreg, t1norm}, t1norm_subject_level }] }] }
const fs = require("fs");
const pptxgen = require("pptxgenjs");

const [payloadPath, outPath] = process.argv.slice(2);
const P = JSON.parse(fs.readFileSync(payloadPath, "utf8"));
const INK = "1F2937", MUTED = "6B7280", FAINT = "9CA3AF", BORDER = "D9DDE3", AMBER = "B45309";
const LC = { INCLUDE: "2E7D32", CAUTION: "E8890C", EXCLUDE: "C62828" };
const AR = 1108 / 586;

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";

{
  const s = pres.addSlide();
  s.background = { color: "FFFFFF" };
  s.addText(P.title, { x: 0.9, y: 2.3, w: 11.6, h: 0.8, fontSize: 32, bold: true, color: INK, fontFace: "Calibri", margin: 0 });
  s.addText(P.subtitle || "", { x: 0.9, y: 3.15, w: 11.7, h: 0.6, fontSize: 15, color: MUTED, fontFace: "Calibri", margin: 0 });
  s.addText(`criteria ${P.criteria_version} · generated ${new Date().toISOString().slice(0, 10)}`,
    { x: 0.9, y: 6.85, w: 6, h: 0.3, fontSize: 10, color: FAINT, fontFace: "Calibri", margin: 0 });
}

let slideNum = 1;
const listing = [];
for (const sec of P.sections) {
  const s = pres.addSlide();
  s.background = { color: "FFFFFF" };
  s.addText(sec.heading, { x: 0.9, y: 3.2, w: 11.6, h: 0.7, fontSize: 30, bold: true, color: sec.color || INK, fontFace: "Calibri", margin: 0 });
  slideNum++;
  for (const c of sec.scans) {
    slideNum++;
    const sl = pres.addSlide();
    sl.background = { color: "FFFFFF" };
    const m = c.metrics || {};
    sl.addText([
      { text: c.sub, options: { fontSize: 24, bold: true, color: INK } },
      { text: `  ·  ${c.ses}  ·  TR ${(m.tr || 0).toFixed(2)} s`, options: { fontSize: 17, color: MUTED } },
    ], { x: 0.45, y: 0.12, w: 9.2, h: 0.46, fontFace: "Calibri", margin: 0 });
    sl.addText(`Session FD mean ${fmt(m.mean_fd, 3)} / max ${fmt(m.max_fd, 2)} mm  |  outliers ${fmt(m.outlier_percent, 1)}%  |  retained ${fmt(m.retained_minutes, 1)} min  |  ${m.n_volumes} vols`,
      { x: 0.45, y: 0.57, w: 10.4, h: 0.26, fontSize: 11.5, color: MUTED, fontFace: "Calibri", margin: 0 });
    sl.addText(c.note || "", { x: 0.45, y: 0.83, w: 10.6, h: 0.23, fontSize: 10.5, italic: true, bold: !!c.verify, color: c.verify ? AMBER : FAINT, fontFace: "Calibri", margin: 0 });
    sl.addText(c.status, { shape: pres.ShapeType.roundRect, rectRadius: 0.08, x: 11.25, y: 0.18, w: 1.62, h: 0.5, fill: { color: LC[c.status] }, fontSize: 16, bold: true, color: "FFFFFF", align: "center", fontFace: "Calibri" });
    if (c.verify) sl.addText("VERIFY", { shape: pres.ShapeType.roundRect, rectRadius: 0.06, x: 11.25, y: 0.73, w: 1.62, h: 0.3, fill: { color: "FFFFFF" }, line: { color: AMBER, width: 1.25 }, fontSize: 10, bold: true, color: AMBER, align: "center", fontFace: "Calibri" });

    const cw = 6.9, ch = 5.87;
    panel(sl, "Confounds & carpet plot", 0.45, 1.06, cw, ch, c.figures.carpet, true);
    const rx = 7.62, rw = 5.3, rh = rw / AR;
    panel(sl, "BOLD → T1w registration", rx, 1.06, rw, rh, c.figures.coreg, false);
    panel(sl, "T1w → MNI" + (c.t1norm_subject_level ? "  (subject-level)" : ""), rx, 1.06 + rh + 0.66, rw, rh, c.figures.t1norm, false);
    listing.push({ slide: slideNum, ...c });
  }
}

// summary table with a Keep? column
const per = 22;
for (let i = 0; i < listing.length; i += per) {
  const s = pres.addSlide();
  s.background = { color: "FFFFFF" };
  s.addText("Review list" + (listing.length > per ? `  (${Math.floor(i / per) + 1}/${Math.ceil(listing.length / per)})` : ""),
    { x: 0.55, y: 0.28, w: 12.2, h: 0.5, fontSize: 24, bold: true, color: INK, fontFace: "Calibri", margin: 0 });
  const hdr = ["Slide", "Subject", "Session", "Status", "FD mean", "Out %", "Keep?"].map(t => ({ text: t, options: { bold: true, color: "FFFFFF", fill: { color: "374151" }, align: "center", fontSize: 10 } }));
  const tbl = [hdr];
  listing.slice(i, i + per).forEach((c, j) => {
    const base = { color: INK, fontSize: 9.5, align: "center", fill: { color: j % 2 ? "F3F4F6" : "FFFFFF" } };
    tbl.push([
      { text: String(c.slide), options: base }, { text: c.sub, options: { ...base, align: "left" } },
      { text: c.ses, options: base }, { text: c.status, options: { ...base, bold: true, color: LC[c.status] } },
      { text: fmt(c.metrics.mean_fd, 3), options: base }, { text: fmt(c.metrics.outlier_percent, 1), options: base },
      { text: "", options: base },
    ]);
  });
  s.addTable(tbl, { x: 0.55, y: 0.9, w: 12.25, rowH: 0.26, fontFace: "Calibri", border: { type: "solid", color: "E5E7EB", pt: 0.5 }, valign: "middle", colW: [0.8, 3.0, 1.5, 1.6, 1.5, 1.35, 2.5] });
}

function panel(sl, caption, x, y, w, h, img, contain) {
  sl.addText(caption, { x, y, w, h: 0.24, fontSize: 11, bold: true, color: MUTED, fontFace: "Calibri", margin: 0 });
  sl.addShape(pres.ShapeType.roundRect, { rectRadius: 0.05, x: x - 0.03, y: y + 0.24, w: w + 0.06, h: h + 0.06, line: { color: BORDER, width: 0.75 }, fill: { color: "FFFFFF" } });
  if (img && fs.existsSync(img)) {
    const opts = { path: img, x, y: y + 0.27, w, h };
    if (contain) opts.sizing = { type: "contain", w, h };
    sl.addImage(opts);
  } else {
    sl.addText("figure not available", { x, y: y + 0.27 + h / 2 - 0.2, w, h: 0.4, fontSize: 12, color: FAINT, align: "center", fontFace: "Calibri" });
  }
}
function fmt(v, d) { return (v === null || v === undefined) ? "—" : Number(v).toFixed(d); }

pres.writeFile({ fileName: outPath }).then(() => console.log("written", outPath, slideNum, "slides"));
