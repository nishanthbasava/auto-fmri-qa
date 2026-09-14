#!/usr/bin/env bash
# ACCRE alternative to Modal (data never leaves the cluster).
#   sbatch slurm/train_lora.sbatch configs/lora.yaml
#SBATCH --job-name=qcvlm-lora
#SBATCH --partition=pascal        # or the lab's GPU partition
#SBATCH --gres=gpu:1
#SBATCH --mem=48G
#SBATCH --cpus-per-task=4
#SBATCH --time=06:00:00
#SBATCH --output=logs/lora_%j.out
set -euo pipefail
source "${QC_VENV:-$HOME/qcvlm_env}/bin/activate"
export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"   # pre-download the model on a login node
export HF_HUB_OFFLINE=1
cd "$(dirname "$0")/.."
python -m qcvlm.train_lora --config "${1:-configs/lora.yaml}"
