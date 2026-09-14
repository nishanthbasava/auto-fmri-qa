"""LoRA supervised fine-tuning of Qwen2.5-VL on the figure-review dataset.

    python -m qcvlm.train_lora --config configs/lora.yaml [--dry-run] [--limit N]

What happens, step by step (this is the part to understand, not just run):

  1. Load the base VLM in bf16 (or NF4 4-bit for QLoRA), freeze everything.
  2. Wrap the LANGUAGE model's attention + MLP projections with LoRA adapters
     (PEFT): each W gets a trainable low-rank pair (A: r x k, B: d x r) with
     W' = W + (alpha/r) * B A. ~0.5% of the parameters train; the rest stay
     frozen, so memory and checkpoint size are tiny and the base model's vision
     is untouched.
  3. Each example -> chat template with images -> tokens. The LOSS IS MASKED to
     the assistant turn only (-100 elsewhere): the model learns to produce the
     JSON label, not to predict the prompt or the image tokens.
  4. Standard causal-LM cross-entropy, AdamW, cosine schedule, gradient
     accumulation to an effective batch of 16, gradient checkpointing.
  5. At each epoch end, generate on N validation scans and score macro-F1 with
     the same harness used for the API baseline; keep the best adapter.

STATUS: written against transformers 4.45+ / PEFT 0.12 / torch 2.3 and
dry-run checked (data + config + formatting) without a GPU. First real run
pending (see the README status table).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import yaml

from .dataset import load_split
from .formatting import to_qwen_messages


def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    for key in ("model_id", "data_dir", "output_dir", "lora", "train"):
        if key not in cfg:
            raise ValueError(f"{path}: missing '{key}'")
    return cfg


# ----------------------------------------------------------------- data

class ReviewCollator:
    """Batch of examples -> model inputs with assistant-only labels."""

    def __init__(self, processor, max_pixels: int):
        self.processor = processor
        self.max_pixels = max_pixels

    def __call__(self, examples: list[dict]) -> dict:
        from qwen_vl_utils import process_vision_info
        full_texts, prompt_texts, images = [], [], []
        for ex in examples:
            msgs = to_qwen_messages(ex, include_assistant=True, max_pixels=self.max_pixels)
            full_texts.append(self.processor.apply_chat_template(msgs, tokenize=False))
            prompt_texts.append(self.processor.apply_chat_template(
                msgs[:-1], tokenize=False, add_generation_prompt=True))
            imgs, _ = process_vision_info(msgs)
            images.append(imgs)
        flat_images = [im for group in images for im in group]
        batch = self.processor(text=full_texts, images=flat_images or None,
                               padding=True, return_tensors="pt")
        labels = batch["input_ids"].clone()
        labels[batch["attention_mask"] == 0] = -100
        # mask everything up to and including the generation prompt
        for i, ptxt in enumerate(prompt_texts):
            n_prompt = len(self.processor(text=[ptxt], images=images[i] or None,
                                          return_tensors="pt")["input_ids"][0])
            labels[i, :n_prompt] = -100
        batch["labels"] = labels
        return batch


class ListDataset:
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.rows[i]


# ----------------------------------------------------------------- model

def build_model(cfg: dict):
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
    t = cfg["train"]
    kw = {"torch_dtype": torch.bfloat16 if t.get("bf16", True) else torch.float32,
          "device_map": "auto"}
    if t.get("load_in_4bit"):
        from transformers import BitsAndBytesConfig
        kw["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(cfg["model_id"], **kw)
    if t.get("load_in_4bit"):
        model = prepare_model_for_kbit_training(model)
    if t.get("gradient_checkpointing", True):
        model.gradient_checkpointing_enable()
        model.enable_input_require_grads()
    lc = cfg["lora"]
    exclude = re.compile(lc.get("exclude_modules_regex", "^visual\\."))
    targets = [name for name, _ in model.named_modules()
               if name.split(".")[-1] in set(lc["target_modules"]) and not exclude.search(name)]
    peft_cfg = LoraConfig(r=lc["r"], lora_alpha=lc["alpha"], lora_dropout=lc["dropout"],
                          target_modules=targets, bias="none", task_type="CAUSAL_LM")
    model = get_peft_model(model, peft_cfg)
    model.print_trainable_parameters()
    processor = AutoProcessor.from_pretrained(cfg["model_id"], max_pixels=cfg["max_pixels"])
    return model, processor


# ----------------------------------------------------------------- eval callback

def make_eval_callback(cfg: dict, val_examples: list[dict], processor):
    from transformers import TrainerCallback

    from .metrics import macro_f1
    from .predictors.qwen import QwenPredictor
    from .schema import RATINGS

    class EpochEval(TrainerCallback):
        best = -1.0

        def on_epoch_end(self, args, state, control, model=None, **kw):
            n = cfg["train"].get("eval_examples", 64)
            p = QwenPredictor(model_id=cfg["model_id"], max_pixels=cfg["max_pixels"])
            p._model, p._processor = model, processor
            model.eval()
            preds = [p.predict(ex) for ex in val_examples[:n]]
            model.train()
            f1 = macro_f1([e["label"]["rating"] for e in val_examples[:n]],
                          [q["rating"] for q in preds], RATINGS)
            state.log_history.append({"epoch": state.epoch, "val_macro_f1": f1})
            print(f"[epoch {state.epoch:.0f}] validation macro-F1 = {f1:.3f} (n={n})")
            if f1 > self.best:
                self.best = f1
                model.save_pretrained(os.path.join(cfg["output_dir"], "best"))
                with open(os.path.join(cfg["output_dir"], "best", "VAL_F1"), "w") as f:
                    f.write(f"{f1:.4f}\n")
    return EpochEval()


# ----------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="configs/lora.yaml")
    ap.add_argument("--dry-run", action="store_true",
                    help="load config + data, print the first formatted example, no torch")
    ap.add_argument("--limit", type=int, default=None, help="train on the first N examples (smoke)")
    ap.add_argument("--set", action="append", default=[],
                    help="override config keys, e.g. --set lora.r=8 --set max_pixels=200704")
    args = ap.parse_args(argv)
    cfg = load_config(args.config)
    for item in args.set:
        k, v = item.split("=", 1)
        d = cfg
        *parents, last = k.split(".")
        for p in parents:
            d = d[p]
        d[last] = yaml.safe_load(v)

    train = load_split(cfg["data_dir"], "train")
    val = load_split(cfg["data_dir"], "validation")
    if args.limit:
        train = train[:args.limit]
    print(f"train {len(train)} examples, validation {len(val)}; model {cfg['model_id']}; "
          f"LoRA r={cfg['lora']['r']} alpha={cfg['lora']['alpha']}; max_pixels {cfg['max_pixels']}")
    if args.dry_run:
        msgs = to_qwen_messages(train[0], include_assistant=True, max_pixels=cfg["max_pixels"])
        print("--- first example, Qwen chat form ---")
        for m in msgs:
            c = m["content"] if isinstance(m["content"], str) else \
                " ".join(b["text"] if b["type"] == "text" else f"<image {b['image']}>" for b in m["content"])
            print(f"[{m['role']}] {c[:400]}{'…' if len(c) > 400 else ''}")
        print("dry run OK (no model loaded)")
        return 0

    import torch  # noqa: F401  (fail early with a clear message if the GPU stack is missing)
    from transformers import Trainer, TrainingArguments
    t = cfg["train"]
    model, processor = build_model(cfg)
    os.makedirs(cfg["output_dir"], exist_ok=True)
    with open(os.path.join(cfg["output_dir"], "config.used.yaml"), "w") as f:
        yaml.safe_dump(cfg, f)
    targs = TrainingArguments(
        output_dir=cfg["output_dir"], num_train_epochs=t["epochs"], learning_rate=t["lr"],
        lr_scheduler_type=t.get("scheduler", "cosine"), warmup_ratio=t.get("warmup_ratio", 0.05),
        per_device_train_batch_size=t["per_device_batch"],
        gradient_accumulation_steps=t["grad_accum"], bf16=t.get("bf16", True),
        gradient_checkpointing=t.get("gradient_checkpointing", True),
        weight_decay=t.get("weight_decay", 0.0), max_grad_norm=t.get("max_grad_norm", 1.0),
        logging_steps=t.get("logging_steps", 5), save_strategy="epoch", save_total_limit=2,
        seed=t.get("seed", 7), report_to=cfg.get("report_to", "none"),
        remove_unused_columns=False, dataloader_num_workers=2)
    trainer = Trainer(model=model, args=targs, train_dataset=ListDataset(train),
                      data_collator=ReviewCollator(processor, cfg["max_pixels"]),
                      callbacks=[make_eval_callback(cfg, val, processor)])
    t0 = time.time()
    trainer.train()
    model.save_pretrained(os.path.join(cfg["output_dir"], "final"))
    with open(os.path.join(cfg["output_dir"], "train_log.json"), "w") as f:
        json.dump({"seconds": round(time.time() - t0), "log_history": trainer.state.log_history}, f, indent=1)
    print(f"done in {(time.time() - t0) / 60:.1f} min -> {cfg['output_dir']}/{{best,final}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
