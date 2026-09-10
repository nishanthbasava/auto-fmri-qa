import argparse, csv, os
ap = argparse.ArgumentParser()
ap.add_argument("run_dir"); ap.add_argument("-o", "--out", default="lists")
a = ap.parse_args()
rows = {"INCLUDE": [], "CAUTION": [], "EXCLUDE": []}
for r in csv.DictReader(open(os.path.join(a.run_dir, "scans.csv"))):
    rows[r["status"]].append(r)
os.makedirs(a.out, exist_ok=True)
cols = ["subject","session","tr_s","n_volumes","mean_fd","max_fd","outlier_percent"]
for st, name in [("INCLUDE","included_scans.csv"),("CAUTION","caution_scans.csv"),
                 ("EXCLUDE","excluded_scans.csv")]:
    out = sorted(rows[st], key=lambda r: (r["subject"], r["session"]))
    with open(os.path.join(a.out, name), "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for r in out: w.writerow([r[c] for c in cols])
    print(f"{st:8s} {len(out):3d} -> {a.out}/{name}")
