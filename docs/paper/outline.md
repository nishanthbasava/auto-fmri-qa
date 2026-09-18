# Manuscript outline (working)

Target: methods paper on hybrid deterministic + VLM quality control for
resting-state fMRI derivatives, validated on ADNI. Venue candidates:
NeuroImage / Imaging Neuroscience (methods), OHBM as the earlier venue.
Numbers marked [P] are pending (need human decisions / labels / GPU runs);
everything else is already measured and lives in docs/results.md.

## 1. Introduction

- Manual QC of fMRIPrep outputs does not scale (458 scans here; consortium
  datasets are 10-100x) and is inconsistent across raters.
- Automated metric thresholds (FD/DVARS) are necessary but blind to a class of
  acquisition failures (truncated FOV, misregistration, saturated EPI).
- Claim: a deterministic, versioned criteria engine plus an *advisory* vision
  LLM covers both failure classes while keeping every decision auditable and
  attributable; a fine-tuned open model can replace the API dependency. [P]

## 2. Methods

- 2.1 Cohort: ADNI resting-state, 458 scans / 413 subjects, mixed single-band
  (TR 3 s) and multiband (TR 0.607 s), three scanner vendors.
- 2.2 Deterministic pipeline: per-scan (never pooled) metrics from fMRIPrep
  confounds; versioned pydantic-validated criteria; INCLUDE/CAUTION/EXCLUDE +
  VERIFY bands; journaled, resumable runs.
- 2.3 VLM review: RAG-grounded prompt (protocol docs retrieved per scan facts),
  forced tool call schema-validated, advisory-only (flags, never status
  changes); prompt-injection guard; cost accounting.
- 2.4 Review app: roles, append-only decisions + audit (DB-level REVOKE),
  decisions overlaid on the journal; review-surface metric with misses /
  false alarms reported alongside.
- 2.5 Labeling protocol: two independent raters, Cohen's kappa per field,
  adjudication of disagreements, subject-level splits. [P: kappa]
- 2.6 Fine-tune: Qwen2.5-VL-7B LoRA (vision tower frozen, assistant-only
  loss), vs Claude baseline under an identical harness; ablations
  resolution x RAG context x label granularity. [P]

## 3. Results

- 3.1 Session pooling flips 18/458 labels (5 hidden problems, 13 penalised
  clean scans) — quantifies a real workflow bug class.
- 3.2 Multiband thresholds: naive TR-scaling implies 4.9x; exceedance-matched
  empirical correction is 1.2x (0.415 mm); percentile ratios 1.11-1.62x;
  respiratory-pseudomotion caveat.
- 3.3 VLM review of all 458 scans / 1,374 figures: $7.40, 0 failed batches;
  ratings by status; 38 clean-metrics scans surfaced only by the LLM,
  including a truncated-FOV scan with clean motion numbers.
- 3.4 Review surface: 66-71% reduction metrics-only; 58-62% with the LLM's
  additional catches; misses / false alarms vs human decisions. [P: decisions]
- 3.5 Inter-rater agreement and gold dataset composition. [P]
- 3.6 Fine-tuned model vs API baseline: macro-F1 (bootstrap CI over subjects),
  $/1k images, s/example; ablation grid. [P]

## 4. Discussion

- Advisory-only integration as the safety property: the model widens the
  review surface, never narrows it; every number the model sees was computed
  first.
- Attribution and auditability as first-class requirements for clinical-
  adjacent QC (append-only decisions, no anonymous actions).
- Limitations: single cohort, elderly population priors baked into the prompt,
  respiratory pseudomotion unresolved without notch filtering, VLM ratings not
  a substitute for human review on surfaced scans.
- Release: pipeline + synthetic cohort generator public; no ADNI data or
  identifiers leave the lab network.

## Figures (draft list)

1. System diagram (pipeline -> review -> app -> reports).
2. Pooling flip waterfall (18 flips by direction).
3. SB vs MB FD percentile ratios + threshold comparison.
4. Review-surface Sankey: 458 -> {EXCLUDE, CAUTION, VERIFY, LLM-only, clean}.
5. Example metrics-blind catches (synthetic recreations, not ADNI images).
6. [P] kappa / confusion matrices; F1-vs-cost frontier for Claude vs Qwen-LoRA.
