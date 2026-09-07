# Architecture

## Pipeline (deterministic)

    discover  → find scans by filename convention; validate completeness per scan
    metrics   → per-volume FD/std_dvars from confounds TSV → per-scan mean/max FD,
                scan-median DVARS, outlier% under the configured definition, retained minutes
    classify  → EXCLUDE / CAUTION / INCLUDE + amber VERIFY flags (borderline bands)
    render    → fMRIPrep SVGs → JPEG via headless chromium. Registration reportlets are
                two-layer flicker SVGs; we remove the `.foreground-svg` layer so the
                *subject* image renders (the naive render shows the template — identical
                across subjects; the renderer md5-checks against this failure mode)

All stage outputs land in runs/<run>/ and are recorded in state.json.

## Agent layers (judgment only)

- **figure review** (vision): batches rendered figures to the model with a QC checklist;
  returns structured JSON (rating, note, concern level) per scan. Catches what metrics
  can't: truncated FOV, saturated/ghosted EPI, misregistration, failed skull strip.
- **findings writer**: turns run stats + review JSON into the summary slide bullets.
  Never invents numbers — it is handed the computed values and forbidden to compute.

Known metric blind spots that motivate the review layer (all observed in the ADNI pass):
truncated FOV with clean motion metrics; sharp carpet intensity blocks with quiet FD;
site-clustered EPI saturation. See lab deck for the vendor DVARS shift and the
multiband/TR-scaling trap (respiratory pseudomotion at TR≈0.6s).

## Reporting

- review deck: one slide per flagged scan (carpet + coreg + T1w→MNI, session metrics,
  status chip, VERIFY chip), section per status, summary table with a Keep? column
- dashboard: single static HTML file — sortable scan table, thumbnails, filters; no server

## Provenance rules

- metrics are per scan (session); never pool sessions of a subject
- criteria.yaml is versioned+dated; every artifact footer prints its version
- LLM output is advisory: it can flag (VERIFY) but never changes a computed status
