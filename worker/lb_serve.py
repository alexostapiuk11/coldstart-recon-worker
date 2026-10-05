"""Start `vllm serve` for artifact 2's load-balancing endpoint.

The engine must be the one the service curve measured, or the gate compares
the simulator against a different system. So the command is the curve's
`served_cmd` (data/a2/service-curve.json; tests/test_lb_serve.py compares
them), with one addition: the middleware that stamps worker id and server
latency (a2_middleware.py).

And one deliberate change: `--max-num-seqs 128`, not the curve's 256
(amendment 2026-10-04, second). The simulator admits at most 128 requests per
replica, the curve's top level, and queues the rest. At 256 the engine would
run requests the simulator queues, in a range the curve never measured (level
256 died of CUDA out of memory). No measured level exceeded 128, so the curve
never ran into its 256 limit and still describes this engine. The port comes from the platform's PORT variable;
the endpoint's HEALTH_CHECK_PATH is set to vLLM's own /health.

`exec`, not a subprocess: the platform's signals then reach vLLM directly,
and no Python parent sits between the load balancer and the engine.

All four variables are required, with no defaults. The rejected alternative
is a default (or dropping the flag when a variable is unset): it would start
a different engine than the one measured, and start it without error.
"""

import os

MIDDLEWARE = "a2_middleware.WorkerHeaders"
# The service curve's flags (served_cmd), held fixed except the admission cap,
# which matches the simulator's 128 (see the module docstring).
MAX_NUM_SEQS = "128"
CURVE_FLAGS = ("--max-num-seqs", MAX_NUM_SEQS, "--no-enable-prefix-caching")

# Each required variable, with what a missing one would silently cost.
REQUIRED = {
    "MODEL_ID": "there is no model to serve",
    "MODEL_REVISION": "without --revision the weights are unpinned, so the engine is not the measured one",
    "MAX_MODEL_LEN": "without --max-model-len the KV capacity, and so the engine, differs from the measured curve",
    "PORT": "without PORT the engine listens where the load balancer is not routing",
}


def command(env) -> list[str]:
    """The `vllm serve` argv: the curve's served_cmd, its admission cap at 128,
    plus the middleware.

    Raises KeyError naming the variable and the consequence if a required
    one is unset; see the module docstring for the rejected alternative.
    """
    for name, consequence in REQUIRED.items():
        if not env.get(name):
            raise KeyError(f"{name} is not set: {consequence}")
    return ["vllm", "serve", env["MODEL_ID"], "--port", env["PORT"],
            "--revision", env["MODEL_REVISION"],
            "--max-model-len", env["MAX_MODEL_LEN"],
            *CURVE_FLAGS, "--middleware", MIDDLEWARE]


def main() -> None:
    """Replace this process with vLLM, so no Python parent stays in between."""
    os.execvp("vllm", command(os.environ))


if __name__ == "__main__":
    main()
