#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Optional virtual-environment activation
# ============================================================

# This remains useful when run_all_qc.sh is executed directly,
# outside the Slurm wrapper.
if [[ -n "${QC_VENV:-}" ]]; then
    if [[ -f "${QC_VENV}/bin/activate" ]]; then
        # shellcheck disable=SC1090
        source "${QC_VENV}/bin/activate"
    else
        echo "ERROR: QC_VENV=${QC_VENV}, but this file was not found:" >&2
        echo "  ${QC_VENV}/bin/activate" >&2
        exit 1
    fi
fi

# ============================================================
# Directories
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="${SCRIPT_DIR}/scripts"

# May be overridden from the Slurm wrapper.
OUTPUT_DIR="${QC_OUTPUT_DIR:-${SCRIPT_DIR}/output}"

# ADNI fMRIPrep derivatives are now the default rather than CamCAN.
DERIVATIVES_DIR_DEFAULT="/panfs/accrepfs.vampire/data/neurogroup/ADNI/RAW_bids/derivatives"

# The first positional argument overrides the default.
DERIVATIVES_DIR="${1:-${DERIVATIVES_DIR_DEFAULT}}"

mkdir -p "${OUTPUT_DIR}"

# ============================================================
# Dependency and input checks
# ============================================================

if [[ ! -d "${DERIVATIVES_DIR}" ]]; then
    echo "ERROR: derivatives directory does not exist:" >&2
    echo "  ${DERIVATIVES_DIR}" >&2
    exit 1
fi

for script in \
    step1_success_qa.py \
    step2_confounds_metrics.py \
    step3_qc_metrics_summary.py \
    step4_first_pass_lists.py \
    step5_manual_sampling.py \
    step6_final_summary.py
do
    if [[ ! -f "${SCRIPTS_DIR}/${script}" ]]; then
        echo "ERROR: missing QC script:" >&2
        echo "  ${SCRIPTS_DIR}/${script}" >&2
        exit 1
    fi
done

python3 - <<'PY'
import numpy
import pandas

print("Required QC Python dependencies found.")
print("numpy:", numpy.__version__)
print("pandas:", pandas.__version__)
PY

echo "QC scripts directory: ${SCRIPTS_DIR}"
echo "fMRIPrep derivatives: ${DERIVATIVES_DIR}"
echo "QC output directory:  ${OUTPUT_DIR}"

# ============================================================
# Step 1
# ============================================================

echo "[1/6] STEP 1 - completeness QA"

python3 "${SCRIPTS_DIR}/step1_success_qa.py" \
    --derivatives-dir "${DERIVATIVES_DIR}" \
    --output-dir "${OUTPUT_DIR}"

# ============================================================
# Step 2
# ============================================================

echo "[2/6] STEP 2 - confounds metrics QA"

python3 "${SCRIPTS_DIR}/step2_confounds_metrics.py" \
    --derivatives-dir "${DERIVATIVES_DIR}" \
    --output-dir "${OUTPUT_DIR}"

# ============================================================
# Step 3
# ============================================================

echo "[3/6] STEP 3 - QC metrics cohort summary"

python3 "${SCRIPTS_DIR}/step3_qc_metrics_summary.py" \
    --output-dir "${OUTPUT_DIR}"

# ============================================================
# Step 4
# ============================================================

echo "[4/6] STEP 4 - first-pass exclude/caution/include"

# Default rules:
#
# Strict exclusion:
#   - Missing required outputs
#   - mean_fd > 0.5 mm
#
# Caution:
#   - motion_outlier_percent > 20%
#
# Additional rules are enabled through QC_* environment variables.

STEP4_ARGS=(
    --output-dir "${OUTPUT_DIR}"
)

[[ "${QC_STRICT_FD_GT_0P5_PERCENT:-0}" == "1" ]] && \
    STEP4_ARGS+=(--enable-strict-fd-gt-0p5-percent)

[[ "${QC_STRICT_MOTION_OUTLIER_PERCENT:-0}" == "1" ]] && \
    STEP4_ARGS+=(--enable-strict-motion-outlier-percent)

[[ "${QC_STRICT_MAX_FD:-0}" == "1" ]] && \
    STEP4_ARGS+=(--enable-strict-max-fd)

[[ "${QC_CAUTION_MEAN_FD:-0}" == "1" ]] && \
    STEP4_ARGS+=(--enable-caution-mean-fd)

[[ "${QC_CAUTION_FD_GT_0P2_PERCENT:-0}" == "1" ]] && \
    STEP4_ARGS+=(--enable-caution-fd-gt-0p2-percent)

[[ "${QC_CAUTION_MAX_FD:-0}" == "1" ]] && \
    STEP4_ARGS+=(--enable-caution-max-fd)

[[ "${QC_CAUTION_FD_GT_0P5_PERCENT:-0}" == "1" ]] && \
    STEP4_ARGS+=(--enable-caution-fd-gt-0p5-percent)

[[ "${QC_CAUTION_STD_DVARS_GT_1P5_PERCENT:-0}" == "1" ]] && \
    STEP4_ARGS+=(--enable-caution-std-dvars-gt-1p5-percent)

python3 "${SCRIPTS_DIR}/step4_first_pass_lists.py" \
    "${STEP4_ARGS[@]}"

# ============================================================
# Step 5
# ============================================================

echo "[5/6] STEP 5 - manual-check sampling lists"

python3 "${SCRIPTS_DIR}/step5_manual_sampling.py" \
    --output-dir "${OUTPUT_DIR}"

# ============================================================
# Step 6
# ============================================================

echo "[6/6] STEP 6 - QC summary"

python3 "${SCRIPTS_DIR}/step6_final_summary.py" \
    --output-dir "${OUTPUT_DIR}"

echo "All QC steps completed."
echo "Outputs are in: ${OUTPUT_DIR}"