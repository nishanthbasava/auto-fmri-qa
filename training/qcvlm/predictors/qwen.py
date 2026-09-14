"""Qwen2.5-VL predictor: zero-shot base model or base + LoRA adapter.

Two backends:
  local     transformers in-process (bf16, optional 4-bit) -- simple, ~1-2 s/image on an A100
  endpoint  an OpenAI-compatible server (vLLM: `vllm serve Qwen/Qwen2.5-VL-7B-Instruct
            --enable-lora --lora-modules qc=<adapter>`) -- 5-10x throughput via
            continuous batching and paged KV cache

    p = QwenPredictor()                                      # zero-shot
    p = QwenPredictor(adapter="adapters/lora-r16")           # fine-tuned
    p = QwenPredictor(endpoint="http://gpu-box:8000/v1", model_id="qc")

`max_pixels` caps the image resolution the processor feeds the model (the
"resolution" axis of the ablation; fewer pixels = fewer visual tokens = cheaper).

STATUS: written against the transformers 4.45+ / PEFT APIs and dry-run checked
with a stub; not yet executed on a GPU (see README status table).
"""
from __future__ import annotations

import base64
import mimetypes

from ..formatting import parse_prediction, to_qwen_messages
from .base import Predictor

DEFAULT_MODEL = "Qwen/Qwen2.5-VL-7B-Instruct"


class QwenPredictor(Predictor):
    name = "qwen"

    def __init__(self, model_id: str = DEFAULT_MODEL, adapter: str | None = None,
                 endpoint: str | None = None, max_pixels: int = 768 * 768,
                 load_in_4bit: bool = False, max_new_tokens: int = 160,
                 temperature: float = 0.0, _http=None, **kw):
        super().__init__(**kw)
        self.model_id, self.adapter, self.endpoint = model_id, adapter, endpoint
        self.max_pixels, self.load_in_4bit = max_pixels, load_in_4bit
        self.max_new_tokens, self.temperature = max_new_tokens, temperature
        self._http = _http
        self._model = self._processor = None

    def ident(self) -> str:
        tag = f"qwen:{self.model_id.split('/')[-1]}"
        if self.adapter:
            tag += f"+lora:{self.adapter.rstrip('/').split('/')[-1]}"
        return f"{tag}@{self.max_pixels}px" + (":4bit" if self.load_in_4bit else "")

    # ------------------------------------------------------------ local backend
    def _load(self):
        if self._model is not None:
            return
        import torch
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
        kw = {"torch_dtype": torch.bfloat16, "device_map": "auto"}
        if self.load_in_4bit:
            from transformers import BitsAndBytesConfig
            kw["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(self.model_id, **kw)
        if self.adapter:
            from peft import PeftModel
            model = PeftModel.from_pretrained(model, self.adapter)
            model = model.merge_and_unload() if not self.load_in_4bit else model
        model.eval()
        self._model = model
        self._processor = AutoProcessor.from_pretrained(self.model_id, max_pixels=self.max_pixels)

    def _predict_local(self, example: dict) -> dict:
        import torch
        from qwen_vl_utils import process_vision_info
        self._load()
        msgs = to_qwen_messages(example, max_pixels=self.max_pixels)
        text = self._processor.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        images, videos = process_vision_info(msgs)
        inputs = self._processor(text=[text], images=images, videos=videos,
                                 padding=True, return_tensors="pt").to(self._model.device)
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=self.max_new_tokens,
                                       do_sample=self.temperature > 0,
                                       temperature=self.temperature or None)
        gen = out[0, inputs["input_ids"].shape[1]:]
        return parse_prediction(self._processor.decode(gen, skip_special_tokens=True))

    # ------------------------------------------------------------ endpoint backend
    @staticmethod
    def _data_url(path: str) -> str:
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as f:
            return f"data:{mime};base64,{base64.b64encode(f.read()).decode()}"

    def _predict_endpoint(self, example: dict) -> dict:
        import httpx
        msgs = to_qwen_messages(example)
        oai = []
        for m in msgs:
            if isinstance(m["content"], str):
                oai.append(m)
                continue
            parts = []
            for b in m["content"]:
                if b["type"] == "text":
                    parts.append({"type": "text", "text": b["text"]})
                else:
                    parts.append({"type": "image_url", "image_url": {"url": self._data_url(b["image"])}})
            oai.append({"role": m["role"], "content": parts})
        body = {"model": self.model_id, "messages": oai, "max_tokens": self.max_new_tokens,
                "temperature": self.temperature}
        post = self._http or httpx.post
        r = post(f"{self.endpoint.rstrip('/')}/chat/completions", json=body, timeout=120)
        r.raise_for_status()
        return parse_prediction(r.json()["choices"][0]["message"]["content"])

    def _predict(self, example: dict) -> dict:
        return self._predict_endpoint(example) if self.endpoint else self._predict_local(example)
