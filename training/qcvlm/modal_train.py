"""Run the LoRA fine-tune on a rented GPU with Modal.

    pip install modal && modal setup
    modal volume create qcvlm-data
    modal volume put qcvlm-data data/processed /data/processed        # + the rendered figures
    modal run qcvlm/modal_train.py --config configs/lora.yaml

The dataset JSONL references image paths; copy the run's figures/ directory to
the volume at the same relative path (or re-point paths with `--rebase`).
Adapters are written back to the volume under /data/adapters/<name>.

DUA note: only push rendered reportlets (no NIfTIs) and only after the PI has
confirmed derived figures may leave the cluster; otherwise use slurm/train_lora.sbatch.
"""
from __future__ import annotations

import modal

APP = "qcvlm-train"
VOLUME = "qcvlm-data"

image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("git")
         .pip_install("torch>=2.3", "transformers>=4.45", "accelerate>=0.33", "peft>=0.12",
                      "qwen-vl-utils>=0.0.8", "bitsandbytes>=0.43", "pyyaml", "pydantic>=2", "Pillow")
         .add_local_dir("qcvlm", "/root/training/qcvlm")
         .add_local_dir("configs", "/root/training/configs")
         .add_local_dir("../autoqa", "/root/autoqa"))

app = modal.App(APP, image=image)
vol = modal.Volume.from_name(VOLUME, create_if_missing=True)


# Qwen2.5-VL is a public checkpoint: no HF token needed. Add
# secrets=[modal.Secret.from_name("huggingface")] for gated models or W&B.
@app.function(gpu="A100-80GB", timeout=6 * 3600, volumes={"/data": vol})
def train(config: str = "configs/lora.yaml", limit: int | None = None, rebase: str | None = None):
    import os
    import sys
    sys.path[:0] = ["/root/training", "/root"]
    os.chdir("/root/training")
    from qcvlm import train_lora
    argv = ["--config", config, "--set", "data_dir=/data/processed",
            "--set", "output_dir=/data/adapters/" + os.path.basename(config).replace(".yaml", "")]
    if limit:
        argv += ["--limit", str(limit)]
    rc = train_lora.main(argv)
    vol.commit()
    return rc


@app.local_entrypoint()
def main(config: str = "configs/lora.yaml", limit: int = 0):
    rc = train.remote(config=config, limit=limit or None)
    print("exit code", rc)
