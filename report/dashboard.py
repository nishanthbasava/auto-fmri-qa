"""Emit a single static HTML dashboard for a run: sortable scan table with
thumbnails, status/verify filters, criteria stamp. No server needed.

    python -m report.dashboard runs/<run>/     ->  runs/<run>/dashboard.html
"""
import argparse
import base64
import html
import json
import os

from pipeline.state import RunState

CSS = """
body{font-family:-apple-system,Segoe UI,sans-serif;margin:24px;color:#1f2937;background:#fff}
h1{font-size:22px;margin:0 0 4px} .sub{color:#6b7280;font-size:13px;margin-bottom:16px}
.chips button{border:1px solid #d9dde3;background:#fff;border-radius:14px;padding:4px 12px;
  margin-right:6px;cursor:pointer;font-size:12px}
.chips button.on{background:#1f2937;color:#fff;border-color:#1f2937}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:12px}
th,td{border-bottom:1px solid #e5e7eb;padding:6px 8px;text-align:left;vertical-align:middle}
th{cursor:pointer;background:#f3f4f6;position:sticky;top:0}
.badge{display:inline-block;padding:2px 8px;border-radius:9px;color:#fff;font-weight:600;font-size:11px}
.INCLUDE{background:#2e7d32}.CAUTION{background:#e8890c}.EXCLUDE{background:#c62828}
.verify{color:#b45309;font-weight:600;font-size:11px}
td img{height:52px;border:1px solid #e5e7eb;border-radius:3px;cursor:pointer}
.note{color:#6b7280;font-size:12px;max-width:340px}
"""

JS = """
function flt(st,btn){document.querySelectorAll('.chips button').forEach(b=>b.classList.remove('on'));
 btn.classList.add('on');
 document.querySelectorAll('tbody tr').forEach(r=>{
   r.style.display=(st==='ALL'||r.dataset.status===st||(st==='VERIFY'&&r.dataset.verify==='1'))?'':'none';});}
function srt(col,num){const tb=document.querySelector('tbody');
 const rows=[...tb.rows]; const dir=tb.dataset['d'+col]==='a'?-1:1; tb.dataset['d'+col]=dir===1?'a':'b';
 rows.sort((a,b)=>{let x=a.cells[col].dataset.v??a.cells[col].innerText,
   y=b.cells[col].dataset.v??b.cells[col].innerText;
   if(num){x=parseFloat(x)||0;y=parseFloat(y)||0;} return (x>y?1:x<y?-1:0)*dir;});
 rows.forEach(r=>tb.appendChild(r));}
"""


def thumb(path, max_bytes=60000):
    """Inline a downscaled thumbnail as data URI (keeps the file portable)."""
    try:
        from PIL import Image
        import io
        im = Image.open(path)
        im.thumbnail((260, 260))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="JPEG", quality=60)
        data = buf.getvalue()
        if len(data) > max_bytes:
            return None
        return "data:image/jpeg;base64," + base64.b64encode(data).decode()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir")
    args = ap.parse_args()
    state = RunState(args.run_dir)
    crit = state.data.get("criteria", {})
    scans = sorted(state.scans().values(), key=lambda s: (s["sub"], s["ses"]))
    counts = {}
    for s in scans:
        counts[s["status"]] = counts.get(s["status"], 0) + 1

    rows = []
    for s in scans:
        m = s["metrics"]
        rev = s.get("review", {})
        carpet = s.get("rendered", {}).get("carpet")
        img = thumb(carpet) if carpet and os.path.exists(carpet) else None
        img_html = (f'<a href="figures/{os.path.basename(carpet)}" target="_blank">'
                    f'<img src="{img}"></a>') if img else ""
        notes = "; ".join(s["reasons"] + s["verify_flags"])
        if rev.get("note"):
            notes += f" | review[{rev.get('rating')}]: {rev['note']}"
        rows.append(
            f'<tr data-status="{s["status"]}" data-verify="{1 if s["verify_flags"] else 0}">'
            f'<td>{s["sub"]}</td><td>{s["ses"]}</td>'
            f'<td><span class="badge {s["status"]}">{s["status"]}</span>'
            f'{"<div class=verify>VERIFY</div>" if s["verify_flags"] else ""}</td>'
            f'<td data-v="{m.get("mean_fd") or 0}">{m.get("mean_fd")}</td>'
            f'<td data-v="{m.get("max_fd") or 0}">{m.get("max_fd")}</td>'
            f'<td data-v="{m.get("outlier_percent") or 0}">{m.get("outlier_percent")}</td>'
            f'<td data-v="{m.get("retained_minutes") or 0}">{m.get("retained_minutes")}</td>'
            f'<td>{img_html}</td><td class="note">{html.escape(notes)}</td></tr>')

    doc = f"""<!doctype html><meta charset="utf-8"><title>fMRI QC dashboard</title>
<style>{CSS}</style><script>{JS}</script>
<h1>fMRI QC dashboard</h1>
<div class="sub">{len(scans)} scans · {" · ".join(f"{k} {v}" for k, v in sorted(counts.items()))}
 · criteria {crit.get("version", "?")} ({crit.get("dated", "?")})
 · outlier mode: {crit.get("outlier_definition", {}).get("mode", "?")}</div>
<div class="chips">
 <button class="on" onclick="flt('ALL',this)">All</button>
 <button onclick="flt('EXCLUDE',this)">Exclude</button>
 <button onclick="flt('CAUTION',this)">Caution</button>
 <button onclick="flt('INCLUDE',this)">Include</button>
 <button onclick="flt('VERIFY',this)">Verify flags</button></div>
<table><thead><tr>
<th onclick="srt(0)">Subject</th><th onclick="srt(1)">Session</th><th onclick="srt(2)">Status</th>
<th onclick="srt(3,1)">Mean FD</th><th onclick="srt(4,1)">Max FD</th><th onclick="srt(5,1)">Out %</th>
<th onclick="srt(6,1)">Retained min</th><th>Carpet</th><th>Notes</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table>"""
    out = os.path.join(args.run_dir, "dashboard.html")
    with open(out, "w") as f:
        f.write(doc)
    print(f"wrote {out} ({os.path.getsize(out) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
