FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first (avoids ~2GB CUDA wheels pulled in by sentence-transformers).
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install optimum for model export (build-time only)
RUN pip install --no-cache-dir optimum[onnxruntime]

COPY download_models.py .
COPY server.py .

# Download (and for ONNX-backend models, quantize) embedding models at build time.
ENV OMP_NUM_THREADS=18
RUN python download_models.py

EXPOSE 8080

CMD ["python", "server.py"]
