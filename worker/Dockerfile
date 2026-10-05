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
# harness/ ships too: worker/handler.py imports harness.recorder once the stage
# recorder moves there. A missing COPY is an ImportError on a paid GPU run and
# nothing in the local loop reveals it, which is why the copy lands before the
# move rather than with it. tests/test_harness_boundary.py asserts these COPY
# lines cover everything the image actually imports.
COPY harness /opt/harness
# artifact 5's package: worker/a5_handler.py and worker/a5_recon_handler.py import it.
COPY multilora /opt/multilora
COPY worker/recon_handler.py /opt/recon_handler.py
COPY worker/probe.py /opt/probe.py
COPY worker/handler.py /opt/handler.py
COPY worker/a5_handler.py /opt/a5_handler.py
COPY worker/a5_recon_handler.py /opt/a5_recon_handler.py
# The service-curve sweep's handler (worker/sweep_handler.py), which runs
# harness/sweep_worker.py inside the container; harness/service_sweep.py is the
# local side and is not called here. Imports only harness/, never coldstart/.
COPY worker/sweep_handler.py /opt/sweep_handler.py
# Artifact 4's worker side: its package (imports only harness/, never
# coldstart/ or autoscale/) and its two handlers, each selected by
# dockerStartCmd like the sweep's.
COPY placement_measure /opt/placement_measure
COPY worker/a4_recon_handler.py /opt/a4_recon_handler.py
COPY worker/a4_measure_handler.py /opt/a4_measure_handler.py
COPY worker/lb_serve.py /opt/lb_serve.py
COPY worker/a2_middleware.py /opt/a2_middleware.py

ENTRYPOINT []
# The measurement handler. recon_handler.py and sweep_handler.py stay in the
# image; select one by overriding dockerStartCmd on the template, e.g.
# `python3 -u /opt/sweep_handler.py` for the service-curve sweep.
CMD ["python3", "-u", "/opt/handler.py"]
