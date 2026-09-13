#!/usr/bin/env bash
#SBATCH --job-name=denoise_qc
#SBATCH --output=/panfs/accrepfs.vampire/data/neurogroup/nishanth/slicetiming_test_philips/fmriprep_qc/logs/denoise_qc_%j.out
#SBATCH --error=/panfs/accrepfs.vampire/data/neurogroup/nishanth/slicetiming_test_philips/fmriprep_qc/logs/denoise_qc_%j.err
#SBATCH --time=01:00:00
#SBATCH --mem=8G
#SBATCH --cpus-per-task=2
set -euo pipefail
QC_ROOT="/panfs/accrepfs.vampire/data/neurogroup/nishanth/slicetiming_test_philips/fmriprep_qc"
source "${QC_VENV:-$HOME/fmriprep_qc_env}/bin/activate"
cd "${QC_ROOT}"
python3 scripts/step7_denoise_qc.py \
  --denoise-dir /panfs/accrepfs.vampire/data/neurogroup/ADNI/RAW_bids/derivatives/post_fmriprep_denoise \
  --expected /panfs/accrepfs.vampire/data/neurogroup/ADNI/code/adni_fmriprep/fmriprep_qc/output/after_manual/fmriprep_final_pass_scans.txt \
  --output-dir output/denoise_qc
