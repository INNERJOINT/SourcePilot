#!/usr/bin/env python3
"""Download embedding models at Docker build time.

All models use the ONNX INT8 backend (AVX-512 VNNI) for fast CPU inference.
- BAAI/bge-base-zh-v1.5: exported + quantized via optimum.
- nomic-ai/CodeRankEmbed: pulled as a pre-built ONNX from
  sirasagi62/code-rank-embed-onnx, then dynamically quantized to INT8.
"""

import os
from pathlib import Path

MODEL_DIR = os.environ.get("EMBEDDING_MODEL_DIR", "/app/models")

# (hf_name, output_subdir, backend)
# - "onnx-int8":     export from a transformers checkpoint via optimum, then quantize.
# - "onnx-prebuilt": snapshot-download a repo that already ships model.onnx, then quantize.
MODELS = [
    ("sirasagi62/code-rank-embed-onnx", "CodeRankEmbed", "onnx-prebuilt"),
    ("BAAI/bge-base-zh-v1.5", "bge-base-zh-v1.5", "onnx-int8"),
    ("microsoft/unixcoder-base", "unixcoder-base", "onnx-int8"),
]


def export_and_quantize_onnx(hf_name: str, output_dir: str) -> None:
    """Export to ONNX and quantize to INT8 for AVX-512 VNNI."""
    from optimum.onnxruntime import ORTModelForFeatureExtraction, ORTQuantizer
    from optimum.onnxruntime.configuration import AutoQuantizationConfig

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[onnx] Exporting {hf_name} to ONNX...")
    model = ORTModelForFeatureExtraction.from_pretrained(hf_name, export=True)
    model.save_pretrained(str(out))

    print(f"[onnx] Quantizing {hf_name} to INT8 (AVX-512 VNNI)...")
    qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=False)
    quantizer = ORTQuantizer.from_pretrained(str(out))
    quantizer.quantize(save_dir=str(out), quantization_config=qconfig)

    tokenizer_path = out / "tokenizer.json"
    if not tokenizer_path.exists():
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(hf_name)
        tokenizer.save_pretrained(str(out))
    print(f"[onnx] Done: {out}")


def download_and_quantize_prebuilt_onnx(hf_name: str, output_dir: str) -> None:
    """Snapshot-download a pre-built ONNX repo, then dynamically quantize to INT8.

    Used for models whose custom architecture (e.g. nomic_bert) cannot be exported
    by optimum, but where a community ONNX release is available.
    """
    from huggingface_hub import snapshot_download
    from onnxruntime.quantization import QuantType, quantize_dynamic

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"[onnx-prebuilt] Snapshot downloading {hf_name} -> {out}")
    snapshot_download(repo_id=hf_name, local_dir=str(out))

    src_onnx = out / "model.onnx"
    if not src_onnx.exists():
        raise FileNotFoundError(f"Expected model.onnx in {out}")

    quantized = out / "model_quantized.onnx"
    print(f"[onnx-prebuilt] Dynamic-quantizing {src_onnx} -> {quantized} (INT8/QUInt8)")
    quantize_dynamic(
        model_input=str(src_onnx),
        model_output=str(quantized),
        weight_type=QuantType.QUInt8,
    )

    # Free disk: keep only the quantized ONNX (server prefers model_quantized.onnx).
    src_onnx.unlink()
    print(f"[onnx-prebuilt] Removed FP32 model.onnx, kept {quantized.name}")

    if not (out / "tokenizer.json").exists():
        raise FileNotFoundError(f"tokenizer.json missing in {out}")
    print(f"[onnx-prebuilt] Done: {out}")


def main() -> None:
    for hf_name, dir_name, backend in MODELS:
        output_dir = os.path.join(MODEL_DIR, dir_name)
        if backend == "onnx-int8":
            export_and_quantize_onnx(hf_name, output_dir)
        elif backend == "onnx-prebuilt":
            download_and_quantize_prebuilt_onnx(hf_name, output_dir)
        else:
            raise ValueError(f"Unknown backend: {backend}")
    print("All models prepared.")


if __name__ == "__main__":
    main()
