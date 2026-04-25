#!/usr/bin/env python3
"""Download embedding models at Docker build time.

Two backends:
- ONNX INT8 (AVX-512 VNNI): standard BERT models exportable by optimum.
- PyTorch (sentence-transformers): models with custom architectures
  (e.g. nomic_bert / CodeRankEmbed) that optimum cannot export.
"""

import os
from pathlib import Path

MODEL_DIR = os.environ.get("EMBEDDING_MODEL_DIR", "/app/models")

# (hf_name, output_subdir, backend)
MODELS = [
    ("nomic-ai/CodeRankEmbed", "CodeRankEmbed", "pytorch"),
    ("BAAI/bge-base-zh-v1.5", "bge-base-zh-v1.5", "onnx-int8"),
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


def download_pytorch(hf_name: str, output_dir: str) -> None:
    """Snapshot-download the model into output_dir for SentenceTransformer at runtime.

    Using a self-contained directory (not the HF cache) keeps the runtime image
    self-sufficient and avoids HF hub network calls on container start.
    """
    from huggingface_hub import snapshot_download

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    print(f"[pytorch] Snapshot downloading {hf_name} -> {out}")
    snapshot_download(
        repo_id=hf_name,
        local_dir=str(out),
    )

    # Smoke-test: load with sentence-transformers to fail fast at build time.
    print(f"[pytorch] Smoke-testing {hf_name} load...")
    from sentence_transformers import SentenceTransformer
    st = SentenceTransformer(str(out), trust_remote_code=True)
    emb = st.encode(["test"])
    assert emb.shape[-1] == 768, f"Expected dim 768, got {emb.shape[-1]}"
    print(f"[pytorch] Done: {out} (dim={emb.shape[-1]})")


def main() -> None:
    for hf_name, dir_name, backend in MODELS:
        output_dir = os.path.join(MODEL_DIR, dir_name)
        if backend == "onnx-int8":
            export_and_quantize_onnx(hf_name, output_dir)
        elif backend == "pytorch":
            download_pytorch(hf_name, output_dir)
        else:
            raise ValueError(f"Unknown backend: {backend}")
    print("All models prepared.")


if __name__ == "__main__":
    main()
