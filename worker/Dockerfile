# Pinned by digest rather than tag. The artifact's reproducibility claim requires that
# a reader rebuilding this image gets the same engine, and `latest` drifts. Resolved
# 2026-08-19 from vllm/vllm-openai:latest; the vLLM version inside is recorded by the
# reconnaissance run and published alongside the results.
ARG VLLM_DIGEST=sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967
FROM vllm/vllm-openai@${VLLM_DIGEST}

ENV HF_HOME=/runpod-volume/hf
ENV VLLM_CACHE_ROOT=/root/.cache/vllm
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r /opt/requirements.txt

COPY recon_handler.py /opt/recon_handler.py
COPY probe.py /opt/probe.py
COPY handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python", "-u", "/opt/recon_handler.py"]
