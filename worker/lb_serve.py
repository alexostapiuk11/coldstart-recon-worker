"""Start `vllm serve` for artifact 2's load-balancing endpoint.

The engine must be the one the service curve measured, or the gate compares
the simulator against a different system. So the command is the curve's
`served_cmd` (data/a2/service-curve.json; tests/test_lb_serve.py compares
them), with one addition: the middleware that stamps worker id and server
latency (a2_middleware.py). The port comes from the platform's PORT variable;
the endpoint's HEALTH_CHECK_PATH is set to vLLM's own /health.

`exec`, not a subprocess: the platform's signals then reach vLLM directly,
and no Python parent sits between the load balancer and the engine.
"""

import os

MIDDLEWARE = "a2_middleware.WorkerHeaders"
# The service curve's flags (served_cmd), held fixed.
CURVE_FLAGS = ("--max-num-seqs", "256", "--no-enable-prefix-caching")


def command(env) -> list[str]:
    cmd = ["vllm", "serve", env["MODEL_ID"], "--port", env.get("PORT", "8000")]
    if env.get("MODEL_REVISION"):
        cmd += ["--revision", env["MODEL_REVISION"]]
    if env.get("MAX_MODEL_LEN"):
        cmd += ["--max-model-len", env["MAX_MODEL_LEN"]]
    return [*cmd, *CURVE_FLAGS, "--middleware", MIDDLEWARE]


def main() -> None:
    os.execvp("vllm", command(os.environ))


if __name__ == "__main__":
    main()
