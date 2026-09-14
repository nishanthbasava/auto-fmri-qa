# auto-fmri-qa

[![ci](https://github.com/nishanthbasava/auto-fmri-qa/actions/workflows/ci.yml/badge.svg)](https://github.com/nishanthbasava/auto-fmri-qa/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/nishanthbasava/auto-fmri-qa/branch/main/graph/badge.svg)](https://codecov.io/gh/nishanthbasava/auto-fmri-qa)

Automated QC for [fMRIPrep](https://fmriprep.org) outputs. It computes per-scan
motion/artifact metrics, classifies scans INCLUDE / CAUTION / EXCLUDE under a
versioned, validated criteria file, has a vision LLM review the QC figures for
what metrics cannot see (truncated FOV, saturated EPI, misregistration), and
delivers the results as a review web app with per-user decisions and an audit
log, a PowerPoint deck, and a static dashboard. Built for the ADNI
resting-state cohort (458 scans, 413 subjects, mixed single-band and multiband
protocols) at the Neurdy Lab @ VALIANT.

    pip install -e .[all]
    autoqa demo --out staged/demo          # synthetic cohort, no real data
    autoqa run --input staged/demo --out runs/demo --render
    autoqa audit surface runs/demo

## How it works

    fMRIPrep derivatives ──autoqa stage──▶ light subset (confounds, sidecars, SVGs)
                                                │
              ┌────────────── deterministic pipeline (autoqa/pipeline) ──────────────┐
              │ discover ▶ metrics (FD, std_dvars, outlier %, retained min) ▶ classify │
              │           ▶ render (SVG ▶ JPEG, template-layer guard)                  │
              └──────────────────────────── runs/<run>/state.json ─────────────────────┘
                                                │
                    ┌───────────────────────────┼──────────────────────────┐
           LLM figure review              review app                 reports
           (autoqa/agents)                (autoqa/api + web)         (autoqa/report)
           RAG-grounded, schema-enforced  users · roles · JWT        pptx deck
           tool call; advisory only       decisions + audit (Postgres) HTML dashboard
                    │
           training/qcvlm: labels (κ) ▶ subject-split dataset ▶ eval harness
                          ▶ Claude baseline vs Qwen2.5-VL (+LoRA) ▶ ablations

**Design principle.** Everything deterministic is plain code; the model is
used only where judgment lives — looking at figures. The LLM can add a VERIFY
flag; it never changes a computed status, and every number it is shown was
computed first.

## Status

What is live, and what the repo does not yet claim.

| area | state | evidence |
|---|---|---|
| Deterministic pipeline, criteria contract, CLI + Python SDK | **live** | `autoqa run`, `autoqa.qc()`, 100% coverage on `pipeline/metrics.py` and `classify.py` |
| Synthetic cohort, 76 tests, CI (lint · 3.10–3.12 matrix · coverage gate · chromium · web · docker) | **live** | `pytest`, badge above |
| Session-pooling audit, review-surface metric | **live, run on the ADNI pass** | 18/458 flips; 66–82% fewer scans opened (see below) |
| LLM figure review: retrieval-grounded prompt, forced tool call validated by pydantic, retries, cost accounting | **live** | `autoqa review`, `tests/test_agents.py` (mocked client) |
| Review app: per-user auth (argon2 + JWT), viewer/reviewer/admin, append-only decisions + audit log in Postgres, request metrics | **live on the lab stack** | `docker compose up`, `tests/test_api.py` |
| Labeling sheets + κ, subject-split dataset with manifest, eval harness with bootstrap CIs, Claude baseline | **live** | `python -m qcvlm.labels / dataset / evaluate` |
| Expert-labeled dataset | **in progress** | labeling with the lab; κ reported when the sheets are in |
| Qwen2.5-VL zero-shot + LoRA fine-tune, ablations (resolution × RAG × label granularity) | **code written, not yet run on a GPU** | `training/qcvlm/train_lora.py --dry-run` passes; first run pending |
| Vendor DVARS bias report | **pending cluster run** | needs `Manufacturer` sidecars on ACCRE |
| Public demo deployment (GCP Cloud Run + Cloud SQL, synthetic data only) | **planned** | the ADNI instance stays on the lab network (DUA) |

## Numbers from the ADNI pass

    autoqa audit pooling runs/<run> [--input staged/...]   # per-scan vs subject-pooled labels
    autoqa audit surface runs/<run>                        # how many scans still need human eyes

The lab's original workflow concatenated every session of a subject before
thresholding (`pd.concat` in `lab_qc_scripts/.../step2_confounds_metrics.py`),
so one label covered sessions that could differ. Recomputing the 458-scan pass
both ways under the same criteria flips **18 labels** (5 where pooling hides a
problem, 13 where it penalises a clean scan). The review-surface audit reports
that a reviewer opens **66–82% fewer scans** on that pass (the range spans the
two criteria versions and whether confirmed EXCLUDEs still count), and prints
the misses and false alarms next to it once human decisions exist — the
reduction is never quoted alone.

## Install

    pip install -e .            # core: the deterministic pipeline (pyyaml, pydantic, Pillow)
    pip install -e .[all,dev]   # + rendering, LLM review, web API/DB, test tooling
    playwright install chromium # once, for figure rendering
    pip install -e training[api,dev]   # the ML side (labels, dataset, evals); GPU deps in training/requirements.txt

## Use it from the CLI

    autoqa stage /path/to/derivatives -o staged/batch1 --task rest   # on the cluster: light subset only
    autoqa run --input staged/batch1 --out runs/qc1 --render          # metrics ▶ labels ▶ JPEGs
    autoqa lists runs/qc1 -o lists/                                  # included/caution/excluded CSVs
    autoqa review runs/qc1 [--only flagged] [--no-rag]               # LLM figure review (ANTHROPIC_API_KEY)
    autoqa report deck runs/qc1 --deck review                        # pptx for the lab meeting
    autoqa report dashboard runs/qc1                                 # single-file HTML
    autoqa audit pooling|surface runs/qc1                            # the numbers above
    autoqa serve · autoqa users add <name> --role reviewer · autoqa db upgrade|sync-journal

`autoqa --help` lists everything. Every stage reads and writes
`runs/<run>/state.json`, so stages are re-runnable and idempotent.

## Use it from Python

    import autoqa

    result = autoqa.qc("staged/batch1", out="runs/qc1")
    print(result.counts)                      # {'INCLUDE': 393, 'CAUTION': 45, 'EXCLUDE': 20}
    for s in result.scans:                    # one record per (subject, session) — never pooled
        print(s["sub"], s["ses"], s["status"], s["metrics"]["mean_fd"], s["verify_flags"])

    crit = autoqa.load_criteria("my_criteria.yaml")   # validated: a typo fails here, not mid-run

## Criteria

`autoqa/data/criteria.yaml` is the single source of truth for every threshold
(mean-FD exclusion, per-volume outlier definition in absolute / relative /
TR-scaled form, outlier-% caution, borderline VERIFY bands, fast-TR cutoff). It
is versioned and dated, validated by a pydantic schema at load, stored in every
run's `state.json`, and printed in every deliverable's footer. Override with
`--criteria path.yaml` or `AFQ_CRITERIA`; `autoqa criteria [path]` validates a file.

## Input contract

Any derivatives-shaped tree works — the pipeline only needs, per scan:

    sub-*/[ses-*/]func/*task-*desc-confounds_timeseries.tsv
    sub-*/[ses-*/]func/*bold.json                  (RepetitionTime, Manufacturer)
    sub-*/figures/*.svg                            (coreg, carpet, T1w→MNI)

`autoqa demo` writes a synthetic tree in exactly this shape (simulated motion
traces with per-profile spike rates, respiratory pseudomotion on fast-TR scans,
vendor-offset DVARS, fMRIPrep-style two-layer SVGs). The test suite and the
public demo use it; no ADNI data is ever committed.

## LLM figure review

`autoqa review` batches rendered figures to a vision model with a QC checklist.
Before each batch, passages from `autoqa/data/knowledge/` (ADNI-3 protocols,
motion thresholds, registration review, confounds) are retrieved by each
scan's facts — TR regime, vendor, run length, panels — and placed in the prompt
as reference notes, so a multiband scan is judged against what is normal for a
multiband scan. The model is forced to call a `record_reviews` tool whose schema
is generated from pydantic models; output is validated before it touches the
journal, rate limits are retried with backoff, and token usage / USD are
accumulated per run. `--no-rag` exists so the effect of grounding can be
measured. Ratings are advisory: concern/bad become VERIFY flags.

## Review app

    docker compose up -d --build      # then http://<lab-machine>:8080

Three containers: `db` (Postgres — users, append-only decisions, audit events),
`api` (FastAPI + the pipeline, internal only; migrations run on start) and `web`
(nginx + the React app, proxying `/api`). Accounts have viewer / reviewer /
admin roles; a decision is attributed to the logged-in reviewer and every
login, launch, decision, and deck build is audited with actor, target, and IP.
`/api/metrics` reports p50/p95/p99 latency per route. Walkthrough and Docker
primer in [docs/deploy.md](docs/deploy.md). **ADNI DUA: lab network only —
never expose port 8080 to the internet.**

## Fine-tuned reviewer

`training/qcvlm` is the path from labels to a model that can run on the lab
machine without an API key: labeling sheets with Cohen's / Fleiss' κ and
adjudication, a subject-split dataset builder with a sha256 manifest and data
card, an evaluation harness (macro-F1 with bootstrap CIs over subjects,
per-class P/R/F1, coarse-label metrics, cost and latency), a Claude API
baseline that reuses the production agent, a Qwen2.5-VL predictor
(transformers or vLLM endpoint), and a LoRA SFT trainer with assistant-only
loss masking and per-epoch validation. See [training/README.md](training/README.md)
for the labeling protocol and the current status.

## Development

    pip install -e .[all,dev] && pip install -e training[api,dev]
    pytest                             # 76 tests, synthetic data only, ~3 s
    pytest --cov=autoqa                # CI gates on coverage
    ruff check autoqa tests training   # CI runs this first

CI: lint · pytest on 3.10/3.11/3.12 with a coverage gate · renderer under
chromium · frontend build · both Docker images. Conventional-commit messages;
one concern per commit.

## Layout

    autoqa/
      data/criteria.yaml   every threshold, versioned and dated — the QC contract
      data/knowledge/      protocol + QC reference docs the review agent retrieves from
      criteria.py          pydantic schema for criteria.yaml
      pipeline/            discover → metrics → classify → render; state.json journal
      analysis/            audits over a finished run: pooling flips, review surface
      agents/              figure review (RAG-grounded, schema-enforced), rag.py, schemas.py
      report/              pptx deck builder + static HTML dashboard
      api/                 FastAPI: auth (argon2 + JWT, roles), audit, timing middleware
      db/                  SQLAlchemy models, Alembic migrations, DB → journal sync
      synth.py             synthetic cohort generator (`autoqa demo`)
      stage.py, lists.py, cli.py
    training/qcvlm/        labels · dataset · metrics · predictors (stub, claude, qwen) · train_lora
    web/                   React + Vite review app
    docker/, docker-compose.yml, .github/workflows/ci.yml
    scripts/               cluster-only helpers (sort_qc_scans.py, slurm/, protocol plots)
    lab_qc_scripts/        the lab's original subject-level fmriprep_qc workflow (vendored; see its README)

## Acknowledgements

Built in the Neurdy Lab @ VALIANT (Vanderbilt) on ADNI data (see
[adni.loni.usc.edu](https://adni.loni.usc.edu) for data-use terms). The
vendored `lab_qc_scripts/` are the lab's reference workflow; AutoQA
re-implements its steps 1–4 per scan and adds everything else.
