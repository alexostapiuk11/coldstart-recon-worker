# Pinned by digest rather than tag. The artifact's reproducibility claim requires that
# a reader rebuilding this image gets the same engine, and `latest` drifts. Resolved
# 2026-08-19 from vllm/vllm-openai:latest; the vLLM version inside is recorded by the
# reconnaissance run and published alongside the results.
ARG VLLM_DIGEST=sha256:0a51ea5b4ae2dc5d81890e5173f54203d2a3ae0cfffe51b8fd2afd4391bfd967
FROM vllm/vllm-openai@${VLLM_DIGEST}

ENV HF_HOME=/runpod-volume/hf
ENV VLLM_CACHE_ROOT=/root/.cache/vllm
ENV PYTHONUNBUFFERED=1

# The probe imports the pre-registered warmup trio from coldstart.analysis.metrics
# rather than re-defining it, so the package ships in the image. /opt is on the
# path for both that package and the worker modules beside it.
ENV PYTHONPATH=/opt

COPY worker/requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r /opt/requirements.txt

# Build context is the repository root, not worker/, because the package above
# lives outside worker/. Vendoring a copy into worker/ instead would put a
# second, drifting copy of the pre-registered definitions in the tree.
COPY coldstart /opt/coldstart
COPY worker/recon_handler.py /opt/recon_handler.py
COPY worker/probe.py /opt/probe.py
COPY worker/handler.py /opt/handler.py

ENTRYPOINT []
CMD ["python3", "-u", "/opt/recon_handler.py"]
