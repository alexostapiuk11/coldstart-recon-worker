"""Invented inputs, so the GPU-free half runs end to end before hardware time is bought.

THE NUMBERS ARE INVENTED. Every object here is marked unmeasured or
unregistered, and scripts/a4_sweep.py refuses them unless run with
--allow-unmeasured. The measurement plan replaces all of them.

- The solo curve is artifact 2's placeholder, which is shaped like the 8B
  model, not the 4B one artifact 4 will measure.
- The co-located surface is that curve scaled up by 5% for the memory split
  and by a further 7-33% as the neighbour's load rises.
- Swap times are a plausible spread around 20 s.
- The design's values are proposals, not the registered ones.
"""

from autoscale.service import SERVICE_CURVE_PLACEHOLDER
from placement.colocated import ColocatedSurface
from placement.design import Design
from placement.money import Assumptions
from placement.resample import EmpiricalDistribution
from placement.sim import Engines

__all__ = ["PLACEHOLDER_DESIGN", "PLACEHOLDER_ENGINES", "PLACEHOLDER_RATE", "PLACEHOLDER_SWAP_TIME"]

COLOCATED_PLACEHOLDER = ColocatedSurface(
    own=(1, 2, 4, 8, 16, 32),
    neighbour=(0, 8, 16, 32),
    latency=(
        (0.315, 0.336, 0.366, 0.42),
        (0.326, 0.347, 0.378, 0.434),
        (0.347, 0.37, 0.403, 0.462),
        (0.399, 0.426, 0.464, 0.532),
        (0.546, 0.582, 0.634, 0.728),
        (0.997, 1.064, 1.159, 1.33),
    ),
    measured=False,
)

PLACEHOLDER_ENGINES = Engines(solo=SERVICE_CURVE_PLACEHOLDER, colocated=COLOCATED_PLACEHOLDER)

PLACEHOLDER_SWAP_TIME = EmpiricalDistribution(
    samples=(17.8, 18.9, 19.6, 20.2, 20.9, 21.7, 23.4, 26.1), measured=False
)

PLACEHOLDER_DESIGN = Design(
    n_models=20,
    offered_gpus=4.0,
    hot_fraction=0.7,
    warmup=120.0,
    mean_burst=30.0,
    duty=0.2,
    skews=(0.6, 1.0, 1.5, 2.0),
    regimes=("spread", "bursty"),
    repetitions=30,
    slo_seconds=4.0,
    pilot_traces=1200,
    seed=17,
    preregistered=False,
)

PLACEHOLDER_RATE = Assumptions(
    gpu_hourly_rate=0.70, provenance="illustrative round number for a 24 GB card, not a quote"
)
