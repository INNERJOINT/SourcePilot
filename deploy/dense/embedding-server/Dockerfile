FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build-time only: optimum (ONNX export) + huggingface_hub (snapshot download).
# These are NOT needed at runtime.
RUN pip install --no-cache-dir optimum[onnxruntime] huggingface_hub

COPY download_models.py .
COPY server.py .

# Download (and quantize) embedding models at build time. All models end up
# as model_quantized.onnx + tokenizer.json under /app/models/<name>/.
# +1 model (UniXcoder) ≈ +5min build, +500MB image
ENV OMP_NUM_THREADS=18
RUN python download_models.py

EXPOSE 8080

CMD ["python", "server.py"]
