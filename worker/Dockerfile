ARG VLLM_TAG=latest
FROM vllm/vllm-openai:${VLLM_TAG}

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
