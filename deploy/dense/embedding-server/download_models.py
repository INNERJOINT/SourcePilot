#!/usr/bin/env python3
"""Download and quantize embedding models to ONNX INT8 at Docker build time."""

import os
from pathlib import Path

MODEL_DIR = os.environ.get("EMBEDDING_MODEL_DIR", "/app/models")

MODELS = {
    "CodeRankEmbed": "nomic-ai/CodeRankEmbed",
    "bge-base-zh-v1.5": "BAAI/bge-base-zh-v1.5",
}


def export_and_quantize(hf_name: str, output_dir: str):
    from optimum.onnxruntime import ORTModelForFeatureExtraction, ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Export to ONNX
    print(f"Exporting {hf_name} to ONNX...")
    model = ORTModelForFeatureExtraction.from_pretrained(hf_name, export=True)
    model.save_pretrained(str(out))

    # Quantize to INT8 (AVX-512 VNNI for i9-9980XE)
    print(f"Quantizing {hf_name} to INT8...")
    qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=False)
    quantizer = ORTQuantizer.from_pretrained(str(out))
    quantizer.quantize(save_dir=str(out), quantization_config=qconfig)
    print(f"Done: {out}")

    # Copy tokenizer.json from HuggingFace cache if not already present
    tokenizer_path = out / "tokenizer.json"
    if not tokenizer_path.exists():
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(hf_name)
        tokenizer.save_pretrained(str(out))
        print(f"Saved tokenizer to {out}")


def main():
    for dir_name, hf_name in MODELS.items():
        output_dir = os.path.join(MODEL_DIR, dir_name)
        export_and_quantize(hf_name, output_dir)
    print("All models exported and quantized.")


if __name__ == "__main__":
    main()
