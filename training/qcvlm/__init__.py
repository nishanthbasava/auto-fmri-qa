"""qcvlm -- data, evaluation and fine-tuning for the AutoQA figure reviewer.

Pipeline:  autoqa run --render  ->  label export/import (+ kappa)  ->  dataset build
           ->  evaluate (Claude baseline, Qwen zero-shot, Qwen+LoRA)  ->  ablations

Everything in this package is GPU-free except the Qwen predictors and the LoRA
trainer, which import torch lazily. Run modules with `python -m qcvlm.<module>`
from the `training/` directory (or `pip install -e training`).
"""
