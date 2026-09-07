# auto-fmri-qa

Automated QA for fMRIPrep outputs: computes per-scan motion/artifact metrics, classifies
scans (INCLUDE / CAUTION / EXCLUDE) under versioned criteria, has an LLM review the QC
figures for problems metrics cannot see (coverage failures, saturated EPI, misregistration),
and generates the review deliverables — PowerPoint decks and a static HTML dashboard.

Built from the ADNI rs-fMRI QC pass (Aug 2026); design notes in `docs/architecture.md`.

## Design principle

Everything deterministic is plain code; the LLM is used only where judgment lives:
looking at figures, writing findings prose, adjudicating borderlines. Metrics, thresholds,
rendering, and deck assembly never depend on a model.

## Layout

    criteria.yaml        every threshold, versioned and dated — the QC contract
    stage_inputs.py      runs ON the cluster: copies the light subset (figures/confounds/
                         sidecars) out of an fMRIPrep derivatives tree (~MBs per subject)
    pipeline/            deterministic stages: discover → metrics → classify → render
    agents/              LLM layers: figure review (vision, structured JSON), findings writer
    report/              deck builder (pptx) + static HTML dashboard
    runs/<timestamp>/    all outputs of one run (gitignored)

## Quick start

    pip install -r requirements.txt && playwright install chromium
    # on the cluster:
    python stage_inputs.py /path/to/derivatives -o staged/
    # locally:
    python -m pipeline.run --input staged/ --criteria criteria.yaml --out runs/$(date +%Y%m%d)
    # optional LLM review + reports (needs ANTHROPIC_API_KEY):
    python -m agents.review_figures runs/<run>/
    python -m report.build_decks runs/<run>/ --deck review
    python -m report.dashboard runs/<run>/

Every stage reads and writes `runs/<run>/state.json`, so stages are re-runnable and
idempotent; a stage skips work whose outputs already exist.

## Input contract

Any derivatives-shaped tree works — the pipeline only needs, per scan:

    sub-*/[ses-*/]func/*task-*desc-confounds_timeseries.tsv
    sub-*/[ses-*/]func/*bold.json                  (RepetitionTime)
    sub-*/figures/*.svg                            (coreg, carpet, T1w→MNI)

Pointing `--input` directly at a full derivatives tree on the cluster also works;
`stage_inputs.py` exists so the NIfTIs never need to leave the cluster.

## Deploy (lab machine, Docker)

    docker compose up -d --build     # then open http://<lab-machine>:8080

Two containers: `api` (FastAPI + the whole pipeline, internal-only) and `web`
(nginx serving the React app, proxying `/api`). Secrets come from `.env`
(`APP_PASSWORD`, `ANTHROPIC_API_KEY`); results live in `./runs`, inputs in
`./staged` — both survive rebuilds. Full walkthrough + Docker primer:
[docs/deploy.md](docs/deploy.md). **ADNI DUA: lab network only — never expose
port 8080 to the internet.**
