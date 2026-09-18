# Results from the ADNI pass

Numbers from the real 458-scan / 413-subject ADNI resting-state cohort
(criteria `1.0-draft`, absolute outlier mode). Everything here is reproducible
from the run directory with the commands shown; per-scan detail lives in the
run's `state.json` / `review.json`, which stay on the lab network (ADNI DUA —
no scan identifiers in this file).

## Deterministic pipeline (2026-09-10)

    autoqa run --input staged/adni-full --out runs/optionA

458 scans: **348 INCLUDE / 90 CAUTION / 20 EXCLUDE**.

## Session-pooling audit

    autoqa audit pooling runs/optionA

The lab's original workflow pooled every session of a subject before
thresholding. Recomputing both ways under identical criteria flips
**18 / 458 labels** — 5 where pooling hides a problem, 13 where it penalises a
clean scan.

## LLM figure review (2026-09-18)

    autoqa render runs/optionA && autoqa review runs/optionA --only all

All 458 scans (1,374 rendered figures) reviewed by `claude-sonnet-4-5` with
RAG grounding, 4 scans per call:

| | clean | minor | concern | bad |
|---|---|---|---|---|
| flagged scans (CAUTION/EXCLUDE, n=110) | 40 | 28 | 40 | 2 |
| clean-metrics scans (INCLUDE, n=348) | 176 | 122 | 49 | 1 |

**115/115 batches passed schema validation on the first or second attempt, 0
failed. Total cost $7.40** (567k input tokens; system prompt cached across
batches).

What the model caught that motion metrics cannot see:

- **Two truncated-FOV scans rated `bad`** — one of them classified INCLUDE
  with clean metrics (mean FD 0.16 mm, 5% outliers): missing cerebellum and
  inferior temporal lobes. On numbers alone it would have entered the
  analysis.
- A low-contrast / low-signal EPI on an INCLUDE scan (mean FD 0.07 mm) where
  interior alignment cannot be judged.
- 38 INCLUDE scans total (mean FD 0.07–0.34 mm) with visible carpet-plot
  corruption — sharp-edged intensity blocks, signal-dropout bands — that the
  FD/DVARS thresholds cleared.

Notes are ≤140 chars with timestamps, and concern/bad ratings become VERIFY
flags with knowledge-base citations; ratings never change a computed status.

## Review surface

    autoqa audit surface runs/optionA

| | scans a human opens | reduction vs opening all 458 |
|---|---|---|
| metrics only (pre-review) | 155 | 66.2% (strict) / 70.5% (triage) |
| metrics + LLM review | 193 | 57.9% (strict) / 62.2% (triage) |

Attribution of the 193: 20 EXCLUDE + 90 CAUTION + 45 metric-band VERIFY +
**38 surfaced only by the LLM**. The visual review deliberately *spends* some
of the metrics-only reduction to buy coverage of metrics-blind failures —
including the truncated-FOV scan above. Misses / false alarms are reported by
the audit once human decisions exist in the journal; until then the reduction
is quoted unqualified.

## Multiband FD threshold analysis

    python scripts/qc_protocol_plots.py

426 single-band vs 32 multiband scans: naively TR-scaling the 0.5 mm FD spike
threshold implies 0.101 mm (4.9×); matching the single-band exceedance rate
(7.5% of frames) puts the empirical multiband threshold at 0.415 mm — **1.2×**
(per-percentile FD ratios 1.11–1.62×). Caveat: multiband FD includes
respiratory pseudomotion, so an exceedance-matched threshold equalises flag
rates, not physiology; notch-filtered motion parameters remain the principled
fix.
