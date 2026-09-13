> **Origin and scope.** This folder is the Neurdy Lab's original `fmriprep_qc`
> workflow (subject-level completeness + confounds QA, authored in the lab for the
> CamCAN/ADNI preprocessing work and vendored here unchanged as the reference
> implementation). Steps 1–6 are the lab's; steps 7–8 (`step7_denoise_qc.py`,
> `step8_denoise_report.py`) and `run_fmriprep_qc.sh` were added for the ADNI
> denoising pass. AutoQA (the rest of this repository) re-implements steps 1–4
> **per scan** rather than per subject — see `pipeline/` and the pooling audit —
> and adds rendering, LLM review, and the review app.
>
> Sample outputs (`sub-*/`, `sample_denoised.tar.gz`) are ADNI-derived and are
> gitignored; they must not be committed.

# fMRIPrep completeness and QA workflow (`fmriprep_qc`)

This folder implements **6 QA steps**:

1. **Step 1** — Check that each subject has all required fMRIPrep outputs.
2. **Step 2** — Compute confounds-derived metrics.
3. **Step 3** — Write cohort-level QC summary `qa_metrics_summary.txt`.
4. **Step 4** — Generate first-pass exclude / caution / include lists.
5. **Step 5** — Build manual QA sampling lists (and optional plot scripts).
6. **Step 6** — Summarize counts after first-pass and final manual lists.

All outputs default to: `fmriprep_qc/output/`.

**Important (ACCRE):** Steps 2–6 require **`numpy`** and **`pandas`** (`pandas` depends on `numpy`). Login-node **system `python3` usually lacks these packages**, and you often **cannot** `pip install` into system Python. **Always** activate your own venv/conda with dependencies installed before running any QC script or `run_all_qc.sh`. fMRIPrep itself runs via Singularity/Apptainer and is unrelated; this section applies only to **QC scripts in this folder**.

---

## ACCRE cluster: activate your Python environment first

If running e.g. `python3 scripts/step2_confounds_metrics.py` raises:

`ModuleNotFoundError: No module named 'numpy'`

your shell is using an interpreter **without the required packages**. Activate your environment first.

**Option 1 (recommended):** `source` your venv, then run from `fmriprep_qc`:

```bash
source /home/yur5/Documents/mytorch/bin/activate
cd /panfs/accrepfs.vampire/data/neurogroup/runxuan/code/camcan_preprocess/mri/fmriprep_qc
./run_all_qc.sh
```

Replace the `source` path with **your own** venv. The same environment is required when running `python3 scripts/step*.py` step by step.

**Option 2:** Set **`QC_VENV`** to your venv **root** (must contain `bin/activate`); `run_all_qc.sh` will `source` it before calling `python3`:

```bash
QC_VENV=/home/yur5/Documents/mytorch \
  /panfs/accrepfs.vampire/data/neurogroup/runxuan/code/camcan_preprocess/mri/fmriprep_qc/run_all_qc.sh
```

**Slurm jobs:** Before calling `run_all_qc.sh` or individual `step*.py` scripts, add the same `source .../bin/activate` as in your interactive terminal, or `export QC_VENV=...` then run `run_all_qc.sh`.

**Install dependencies** in your **activated** personal environment (do not pip into system Python unless you know what you are doing):

```bash
pip install pandas numpy
```

If the cluster blocks network installs, build wheels elsewhere or use a site module that already includes a scientific stack.

---

## 1. Directory layout

```text
fmriprep_qc/
├── README.md
├── README.en.md
├── run_all_qc.sh
├── pack_manual_qc_samples.sh
├── output/
└── scripts/
    ├── qc_common.py
    ├── step1_success_qa.py
    ├── step2_confounds_metrics.py
    ├── step3_qc_metrics_summary.py
    ├── step4_first_pass_lists.py
    ├── step5_manual_sampling.py
    ├── step5_manual_qa_plots.py
    ├── step5_manual_qa_plots_re.py
    └── step6_final_summary.py
```

---

## 2. Default paths and overrides

- Default **`derivatives`** path:  
  `/panfs/accrepfs.vampire/data/neurogroup/runxuan/datasets/camcan_bids/cc700/mri_bids/derivatives`
- Default **output** path:  
  `/panfs/accrepfs.vampire/data/neurogroup/runxuan/code/camcan_preprocess/mri/fmriprep_qc/output`  
  (relative to repo root: `camcan_preprocess/mri/fmriprep_qc/output`)

Every script supports path overrides (at minimum `--output-dir`; Steps 1–2 also support `--derivatives-dir`).

---

## 3. One-shot run (recommended)

From `fmriprep_qc`, **with numpy/pandas environment activated**:

```bash
./run_all_qc.sh
```

Custom derivatives path:

```bash
./run_all_qc.sh /your/custom/derivatives/path
```

On ACCRE without a pre-activated shell: `QC_VENV=/path/to/venv ./run_all_qc.sh` (see **ACCRE cluster** above).

---

## 4. Step-by-step run

Activate your venv before Steps 2+ (do not use bare login-node `python3` on ACCRE).

```bash
python3 scripts/step1_success_qa.py \
  --derivatives-dir "/path/to/derivatives" \
  --output-dir "./output"

python3 scripts/step2_confounds_metrics.py \
  --derivatives-dir "/path/to/derivatives" \
  --output-dir "./output"

python3 scripts/step3_qc_metrics_summary.py \
  --output-dir "./output"

python3 scripts/step4_first_pass_lists.py \
  --output-dir "./output"

python3 scripts/step5_manual_sampling.py \
  --output-dir "./output"

python3 scripts/step6_final_summary.py \
  --output-dir "./output"
```

---

## 5. Step inputs / outputs

## STEP 1 — Output completeness QA

Script: `scripts/step1_success_qa.py`

For each subject, check **exists and non-empty** (`-s` semantics):

- `derivatives/sub-*.html` (also `derivatives/fmriprep/sub-*.html`)
- `derivatives/sub-*/func/*space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz`
- `derivatives/sub-*/func/*desc-confounds_timeseries.tsv`

Outputs:

- `qa_success_check.csv` (one row per subject)
- `qa_success_summary.txt` (four-line summary)

Example `qa_success_check.csv`:

```text
subject,has_html,has_bold,has_confounds,success
sub-CC110033,1,1,1,1
sub-CC110045,1,1,0,0
```

---

## STEP 2 — Confounds metrics QA

Script: `scripts/step2_confounds_metrics.py`

Output: `qa_confounds_metrics.csv` (one row per subject with a readable confounds TSV). Multiple runs per subject are concatenated vertically before metrics are computed.

### `qa_confounds_metrics.csv` column reference

“High/low” below are **relative** intuitions within a cohort; thresholds should match your study design and site norms.

| Column | Meaning | Higher often suggests | Lower often suggests | Main use |
| --- | --- | --- | --- | --- |
| `subject` | BIDS subject ID | — | — | Align with lists and downstream analysis |
| `n_volume` | Confounds table rows (time points) | Longer scan / TR-related | Shorter scan or truncation | Denominator for percent metrics |
| `mean_fd` | Mean **framewise_displacement** (mm) | Higher average motion | Lower average motion | Overall motion; QC and group covariates |
| `median_fd` | FD median (mm) | Typical epochs more mobile | Typical epochs steadier | Less sensitive to spikes |
| `max_fd` | FD maximum (mm) | Severe transient displacement | No extreme spikes | Flag single large motion events |
| `fd_gt_0p2_count` | Time points with FD **>** 0.2 mm | More “bad” frames at this threshold | Fewer over-threshold frames | Pairs with percent at 0.2 mm |
| `fd_gt_0p2_percent` | `fd_gt_0p2_count / n_volume × 100` | Large fraction over threshold | Most time under threshold | Step 4 caution / exclusion discussion |
| `n_volumes_after_scrubbing` | Time points with FD **<** 0.2 mm (NaN FD excluded) | — | — | Conservative usable volume count at FD &lt; 0.2 |
| `percent_remaining_after_scrubbing` | `n_volumes_after_scrubbing / n_volume × 100` | — | Lower ⇒ less time retained under FD&lt;0.2 rule | Usable fraction if scrubbing at 0.2 mm |
| `fd_gt_0p5_count` / `fd_gt_0p5_percent` | FD **>** 0.5 mm count and percent | More severe motion frames | Fewer | Stricter screening; Step 4 optional strict |
| `mean_dvars` | Temporal mean of **dvars** (fMRIPrep definition) | Larger frame-to-frame differences | Relatively stable | Coarse micro-motion / noise fluctuation |
| `max_dvars` | Max dvars | Strong frame-to-frame jumps | — | Extreme epochs |
| `mean_std_dvars` | Temporal mean of **std_dvars** | Higher standardized DVARS | Lower | Cohort comparison; basis for **z_std_dvars** |
| `max_std_dvars` | Max std_dvars | Extreme standardized fluctuation | — | Coarse outlier epochs |
| `corr_fd_dvars` | Pearson correlation of **FD vs dvars** (≥2 valid pairs) | Motion and DVARS co-vary; changes may be motion-driven | Weak correlation; other sources may dominate | Assess motion-driven signal change |
| `std_dvars_gt_1p5_count` / `std_dvars_gt_1p5_percent` | std_dvars **>** 1.5 count and percent | More high-fluctuation frames | Fewer | Step 4 optional caution |
| `n_motion_outliers` | Count of columns starting with `motion_outlier` | More fMRIPrep spike regressors | Fewer | **Column count (model terms)**, not per-frame 0/1 sum |
| `motion_outlier_percent` | `n_motion_outliers / n_volume × 100` | Higher relative “outlier term” load | Lower | Coarse screen; combine with FD/DVARS/HTML |
| `mean_global_signal` / `std_global_signal` | Mean and SD of **global_signal** | Global drift or fluctuation | Flatter | Global-signal / physiological noise discussion |
| `mean_csf` / `std_csf` | **csf** column stats | CSF level and variability | Lower variability | CSF stability |
| `mean_white_matter` / `std_white_matter` | **white_matter** (fallback **csf_wm**) | WM variability | Lower variability | WM stability |
| `max_abs_trans_*` / `max_abs_rot_*` | Max absolute **trans_*** / **rot_*** (mm or rad) | Large displacement/rotation in that axis | Small extremes | Complement mean_fd by motion type |
| `rms_trans_mean` | Mean per-frame translation RMS | Higher average translation | Lower | Translation summary |
| `rms_rot_mean` | Mean per-frame rotation RMS | Higher average rotation | Lower | Rotation summary |
| `n_a_comp_cor` | Columns prefixed `a_comp_cor_` | More anatomical CompCor terms (pipeline-dependent) | Fewer | Design dimension, not “good/bad” |
| `n_t_comp_cor` | Prefix `t_comp_cor_` | Same | Same | Same |
| `n_c_comp_cor` | Prefix `c_comp_cor_` | Same | Same | Same |
| `n_w_comp_cor` | Prefix `w_comp_cor_` | Same | Same | Same |
| `n_edge_comp` | Prefix `edge_comp` | Same | Same | Same |
| `z_mean_fd` | Cohort **z-score** of `mean_fd` (ddof=1) | Higher motion vs cohort | Lower | Outlier screening (e.g. \|z\|&gt;2/3) |
| `z_std_dvars` | Cohort z-score of `mean_std_dvars` | Higher standardized DVARS vs cohort | Lower | Cohort “volatility outlier” screen |

Notes:

- For **per-frame** motion-outlier proportions, sum values inside `motion_outlier*` columns separately; this table counts **columns**.
- `n_volumes_after_scrubbing` uses **FD &lt; 0.2 mm**; complements `fd_gt_0p2_*` (**&gt;** 0.2).
- `z_mean_fd` and `z_std_dvars` are estimated on **subjects in the current CSV**; re-run Step 2 after adding/removing subjects.
- If `white_matter` is missing, Step 2 falls back to `csf_wm`.

---

## STEP 3 — Cohort QC metrics summary

Script: `scripts/step3_qc_metrics_summary.py`

Runs **after Step 2, before Step 4** (`run_all_qc.sh` follows this order).

Reads `qa_success_check.csv` and `qa_confounds_metrics.csv`, writes **`output/qa_metrics_summary.txt`** with subject counts at common thresholds (totals, missing outputs, mean_fd, max_fd, fd_gt_*_percent, std_dvars_gt_1p5_percent, motion_outlier_percent, etc.).

```bash
python3 scripts/step3_qc_metrics_summary.py --output-dir "./output"
```

---

## STEP 4 — First-pass exclude / caution / include

Script: `scripts/step4_first_pass_lists.py`

Inputs:

- `qa_success_check.csv`
- `qa_confounds_metrics.csv`

Outputs:

- `first_pass_exclude_subjects.txt`
- `first_pass_caution_subjects.txt`
- `first_pass_include_subjects.txt`
- `first_pass_rules.txt`

**Default rules** (`run_all_qc.sh` with no extra flags; thresholds overridable via CLI):

- **Strict exclusion — default (always on)**
  1. Missing required outputs (HTML / preprocessed BOLD / confounds TSV)
  2. `mean_fd > 0.5` mm
- **Strict exclusion — optional** (`--enable-strict-*` or `QC_*=1` in `run_all_qc.sh`)
  - `fd_gt_0p5_percent > 20`% (`--enable-strict-fd-gt-0p5-percent`)
  - `motion_outlier_percent > 50`% (`--enable-strict-motion-outlier-percent`)
  - `max_fd > 5` mm (`--enable-strict-max-fd`)
- **Caution — default (always on)**
  1. `motion_outlier_percent > 20`%
- **Caution — optional** (`--enable-caution-*` or `QC_*=1`)
  - `mean_fd > 0.2` mm (`--enable-caution-mean-fd`)
  - `fd_gt_0p2_percent > 20`% (`--enable-caution-fd-gt-0p2-percent`)
  - `max_fd > 1` mm (`--enable-caution-max-fd`)
  - `fd_gt_0p5_percent > 5`% (`--enable-caution-fd-gt-0p5-percent`)
  - `std_dvars_gt_1p5_percent > 20`% (`--enable-caution-std-dvars-gt-1p5-percent`)

Subjects in strict exclusion are **not** listed under caution.

**Enable all optional rules in `run_all_qc.sh`** (example):

```bash
QC_STRICT_FD_GT_0P5_PERCENT=1 \
QC_STRICT_MOTION_OUTLIER_PERCENT=1 \
QC_STRICT_MAX_FD=1 \
QC_CAUTION_MEAN_FD=1 \
QC_CAUTION_FD_GT_0P2_PERCENT=1 \
QC_CAUTION_MAX_FD=1 \
QC_CAUTION_FD_GT_0P5_PERCENT=1 \
QC_CAUTION_STD_DVARS_GT_1P5_PERCENT=1 \
  ./run_all_qc.sh
```

**Call step4 directly** (default + optional caution example):

```bash
python3 scripts/step4_first_pass_lists.py --output-dir "./output"

# e.g. additionally enable caution: mean_fd > 0.2
python3 scripts/step4_first_pass_lists.py \
  --output-dir "./output" \
  --enable-caution-mean-fd
```

---

## STEP 5 — Manual QA sampling lists

Script: `scripts/step5_manual_sampling.py`

Outputs:

- `top20_mean_fd.txt`
- `top20_max_fd_subjects.txt`
- `top20_std_dvars_subjects.txt`
- `top20_motion_outlier_percent_subjects.txt`
- `median_mean_fd_10_subjects.txt` (10 subjects near median mean_fd)
- `random_5_percent_subjects.txt` (default 5% random sample)
- `sample_for_manual_check.txt` (deduplicated union)

Sampling uses **complete** subjects and prefers `first_pass_include_subjects.txt` for the random draw.

### Step 5 sub-step: batch manual QA plots (Python + Nilearn)

Scripts: `scripts/step5_manual_qa_plots.py` or `scripts/step5_manual_qa_plots_re.py` (refined overlay logic; default plots **02** and **04** only in `_re`).

For subjects given via txt / CLI list / single subject, writes per-subject figures under `output/manualQA/sub-XXXX/`:

1. `*_01_T1w_BOLD_overlay.png` — native mean BOLD edges on T1w (registration QA)
2. `*_02_MNI_BOLD_overlay.png` — masked mean MNI BOLD edges on MNI template
3. `*_03_native_BOLD_mean_ortho.png` / `*_03_native_BOLD_mean_mosaic.png`
4. `*_04_fd_stdDVARS_globalSignal.png` — FD, std DVARS, global signal time series

Examples:

```bash
# txt list
python3 scripts/step5_manual_qa_plots_re.py \
  --subject-list-file "./output/sample_for_manual_check.txt"

# multiple subjects on CLI
python3 scripts/step5_manual_qa_plots_re.py \
  --subjects "sub-CC110033 sub-CC110037 sub-CC110045"

# single subject
python3 scripts/step5_manual_qa_plots_re.py \
  --subject "sub-CC110033"
```

Optional arguments:

- `--derivatives-dir` (default: CamCAN derivatives)
- `--bids-dir` (default: parent of derivatives, i.e. `mri_bids`; fallback for native/raw files)
- `--output-dir` (default: `fmriprep_qc/output/manualQA`)
- `--plots` (`_re` only; default `02,04`)

Notes:

- No FSL required; uses Python + Nilearn.
- MNI overlay is **recomputed** (not copied from fMRIPrep SVG).
- If native preproc BOLD/T1w are missing under derivatives, falls back to `mri_bids/sub-XXXX/anat/*_T1w.nii.gz` and `func/*_bold.nii.gz`.
- Missing inputs for one plot type only skip that figure (warning printed).

**Pack HTML + figures for local review:** `pack_manual_qc_samples.sh` copies fMRIPrep HTML, BOLD, confounds, and `figures/` for subjects in a list.

---

## STEP 6 — Final summary

Script: `scripts/step6_final_summary.py`

After manual QA, maintain:

- `final_exclude_subjects.txt`
- `final_caution_subjects.txt`
- `final_include_subjects.txt`

Output:

- `qc_summary.csv`

Example:

```text
category,count
total_subjects,652
complete_subjects,640
first_pass_exclude,28
first_pass_caution,60
final_exclude,35
final_caution,40
final_include,577
```

If final list files are missing, the script creates empty files before counting.

---

## 6. Recommended workflow

1. Run Steps 1–2 → `qa_success_check.csv`, `qa_confounds_metrics.csv`
2. Run Step 3 → `qa_metrics_summary.txt` (review cohort before setting Step 4 rules)
3. Run Step 4 → first-pass lists
4. Run Step 5 → manual sampling lists (and optional plots)
5. Manual QA → edit final three subject lists
6. Run Step 6 → `qc_summary.csv`

`run_all_qc.sh` order: **Step 1 → 2 → 3 → 4 → 5 → 6**.

---

## 7. Dependencies

- Python 3.8+
- `pandas`
- `numpy`
- `nilearn` / `matplotlib` (manual QA plot scripts only)

Install in your **activated** venv:

```bash
source /path/to/your/venv/bin/activate
pip install pandas numpy nilearn matplotlib
```

Use the same environment at runtime to avoid `No module named numpy` from a different `python3`.

---

## 8. Notes

- Confounds may have multiple runs; Step 2 concatenates per subject before metrics.
- Thresholds are not universal; tune for your study and downstream models.
- First-pass lists are for screening only; final inclusion should follow manual QA (HTML reports + key images).
