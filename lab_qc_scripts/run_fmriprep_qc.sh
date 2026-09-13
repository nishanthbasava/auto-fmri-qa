#!/usr/bin/env bash
#SBATCH --job-name=adni_fmriprep_qc
#SBATCH --output=/panfs/accrepfs.vampire/data/neurogroup/nishanth/slicetiming_test_philips/fmriprep_qc/logs/fmriprep_qc_%j.out
#SBATCH --error=/panfs/accrepfs.vampire/data/neurogroup/nishanth/slicetiming_test_philips/fmriprep_qc/logs/fmriprep_qc_%j.err
#SBATCH --time=04:00:00
#SBATCH --mem=32G
#SBATCH --cpus-per-task=4

set -euo pipefail

QC_ROOT="/panfs/accrepfs.vampire/data/neurogroup/nishanth/slicetiming_test_philips/fmriprep_qc"
DERIVATIVES_DIR="/panfs/accrepfs.vampire/data/neurogroup/ADNI/RAW_bids/derivatives"
OUTPUT_DIR="${QC_ROOT}/output"

QC_VENV="${QC_VENV:-$HOME/fmriprep_qc_env}"

if [[ ! -f "${QC_VENV}/bin/activate" ]]; then
    echo "ERROR: virtual environment not found:"
    echo "${QC_VENV}/bin/activate"
    exit 1
fi

source "${QC_VENV}/bin/activate"

mkdir -p "${OUTPUT_DIR}"

cd "${QC_ROOT}"

QC_OUTPUT_DIR="${OUTPUT_DIR}" \
./run_all_qc.sh "${DERIVATIVES_DIR}"
