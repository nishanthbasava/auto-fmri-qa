# auto-fmri-qa

[![ci](https://github.com/nishanthbasava/auto-fmri-qa/actions/workflows/ci.yml/badge.svg)](https://github.com/nishanthbasava/auto-fmri-qa/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/nishanthbasava/auto-fmri-qa/branch/main/graph/badge.svg)](https://codecov.io/gh/nishanthbasava/auto-fmri-qa)

Automated QA for fMRIPrep outputs: computes per-scan motion/artifact metrics, classifies
scans (INCLUDE / CAUTION / EXCLUDE) under versioned criteria, has an LLM review the QC
figures for problems metrics cannot see (coverage failures, saturated EPI, misregistration),
and generates the review deliverables — PowerPoint decks, a static HTML dashboard, and a
web app where reviewers record keep/drop decisions.

Built from the ADNI rs-fMRI QC pass (Aug 2026); design notes in `docs/architecture.md`.

## Design principle

Everything deterministic is plain code; the LLM is used only where judgment lives:
looking at figures, writing findings prose, adjudicating borderlines. Metrics, thresholds,
rendering, and deck assembly never depend on a model.

## Install

    pip install -e .            # core: the deterministic pipeline (pyyaml, pydantic, Pillow)
    pip install -e .[all,dev]   # + rendering, LLM review, web API, test tooling
    playwright install chromium # once, for figure rendering

## Quick start (CLI)

    # on the cluster: copy the light subset (figures / confounds / sidecars) out
    autoqa stage /path/to/derivatives -o staged/batch1 --task rest
    # locally:
    autoqa run --input staged/batch1 --out runs/$(date +%Y%m%d) --render
    autoqa lists runs/<run> -o lists/                  # included/caution/excluded CSVs
    # optional LLM review + reports (needs ANTHROPIC_API_KEY):
    autoqa rag build
    autoqa review runs/<run>
    autoqa report deck runs/<run> --deck review
    autoqa report dashboard runs/<run>

`autoqa --help` lists every subcommand. Every stage reads and writes
`runs/<run>/state.json`, so stages are re-runnable and idempotent; a stage skips
work whose outputs already exist.

## Quick start (Python)

    import autoqa

    result = autoqa.qc("staged/batch1", out="runs/qc1")
    print(result.counts)                      # {'INCLUDE': 393, 'CAUTION': 45, 'EXCLUDE': 20}
    for s in result.scans:                    # one record per (subject, session)
        print(s["sub"], s["ses"], s["status"], s["metrics"]["mean_fd"], s["verify_flags"])

    crit = autoqa.load_criteria("my_criteria.yaml")   # validated: a typo fails here, not mid-run

## Development

    pip install -e .[all,dev]
    pytest                       # unit suite (synthetic data only; < 1 s)
    pytest --cov=autoqa          # coverage; CI gates on it
    ruff check autoqa tests      # lint (CI runs this first)

CI runs lint, the test matrix (3.10–3.12) with a coverage gate, the renderer
under chromium, the frontend build, and both Docker images on every push.

## Layout

    autoqa/
      data/criteria.yaml   every threshold, versioned and dated — the QC contract
      data/knowledge/      protocol + QC reference docs the review agent retrieves from
      criteria.py          pydantic schema for criteria.yaml; loaded/validated once per run
      analysis/            audits over a finished run: pooling flips, review surface
      pipeline/            deterministic stages: discover → metrics → classify → render
      agents/              LLM layers: figure review (vision, structured JSON) + RAG
      report/              deck builder (pptx) + static HTML dashboard
      api/                 FastAPI backend for the review app (web/ is the React frontend)
      stage.py, lists.py   cluster-side staging; scan-level list export
      cli.py               the `autoqa` command
    scripts/               cluster-only helpers (sort_qc_scans.py, slurm/, protocol plots)
    lab_qc_scripts/        the lab's original subject-level fmriprep_qc workflow (vendored; see its README)
    runs/<timestamp>/      all outputs of one run (gitignored)

## Input contract

Any derivatives-shaped tree works — the pipeline only needs, per scan:

    sub-*/[ses-*/]func/*task-*desc-confounds_timeseries.tsv
    sub-*/[ses-*/]func/*bold.json                  (RepetitionTime)
    sub-*/figures/*.svg                            (coreg, carpet, T1w→MNI)

Pointing `--input` directly at a full derivatives tree on the cluster also works;
`autoqa stage` exists so the NIfTIs never need to leave the cluster.

## Numbers a run can report

    autoqa audit pooling runs/<run> [--input staged/...]   # per-scan vs subject-pooled labels
    autoqa audit surface runs/<run>                        # how many scans still need human eyes

`pooling` reproduces the session-pooling bug: the lab's original workflow
concatenated all of a subject's sessions before thresholding, which changes the
label of a session whenever a clean and a bad session share a subject. On the
458-scan ADNI pass (absolute-DVARS criteria) that flips 18 labels — 5 where
pooling hides a problem, 13 where it penalises a clean scan. `surface` reports
the fraction of the cohort a reviewer no longer has to open (66–82% on that
pass depending on criteria and whether confirmed EXCLUDEs count), alongside the
misses and false alarms once human decisions exist in the journal.

## Criteria

`autoqa/data/criteria.yaml` is the single source of truth for every threshold. Override
with `--criteria path.yaml` or `AFQ_CRITERIA=path.yaml`; `autoqa criteria [path]`
validates and prints a file. Every run stores the criteria it used in `state.json`, and
every deliverable footer prints the version.

## Deploy (lab machine, Docker)

    docker compose up -d --build     # then open http://<lab-machine>:8080

Two containers: `api` (FastAPI + the whole pipeline, internal-only) and `web`
(nginx serving the React app, proxying `/api`). Secrets come from `.env`
(`APP_PASSWORD`, `ANTHROPIC_API_KEY`); results live in `./runs`, inputs in
`./staged` — both survive rebuilds. Full walkthrough + Docker primer:
[docs/deploy.md](docs/deploy.md). **ADNI DUA: lab network only — never expose
port 8080 to the internet.**
