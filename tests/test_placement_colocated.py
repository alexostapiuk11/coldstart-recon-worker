import pytest

from placement.colocated import ColocatedSurface

# latency = 1 + 0.5 * neighbour + 0.25 * (own - 1): bilinear by construction, so
# interpolation must reproduce it exactly anywhere inside the grid.
SURFACE = ColocatedSurface(
    own=(1, 3),
    neighbour=(0, 2),
    latency=((1.0, 2.0), (1.5, 2.5)),
    measured=True,
)


@pytest.mark.parametrize(
    "own, neighbour, expected",
    [(1, 0, 1.0), (3, 2, 2.5), (2, 1, 1.75), (1, 1, 1.5), (3, 0, 1.5)],
)
def test_it_interpolates_bilinearly(own, neighbour, expected):
    assert SURFACE.latency_at(own, neighbour) == pytest.approx(expected)


def test_it_clamps_outside_the_grid_and_says_so():
    assert SURFACE.latency_at(5, 9) == pytest.approx(2.5)
    assert SURFACE.is_extrapolating(5, 1)
    assert SURFACE.is_extrapolating(1, 9)
    assert not SURFACE.is_extrapolating(3, 2)


def test_capacity_is_the_top_measured_own_load():
    assert SURFACE.max_own_concurrency == 3.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"own": (1,), "neighbour": (0, 2), "latency": ((1.0, 2.0),)},
        {"own": (1, 1), "neighbour": (0, 2), "latency": ((1.0, 2.0), (1.0, 2.0))},
        {"own": (1, 3), "neighbour": (0, 2), "latency": ((1.0, 2.0),)},
        {"own": (1, 3), "neighbour": (0, 2), "latency": ((1.0, float("nan")), (1.0, 2.0))},
        {"own": (1, 3), "neighbour": (0, 2), "latency": ((1.0, -2.0), (1.0, 2.0))},
    ],
)
def test_it_refuses_a_table_that_would_misreport_latency(kwargs):
    with pytest.raises(ValueError):
        ColocatedSurface(measured=True, **kwargs)


def test_a_nan_load_is_refused():
    with pytest.raises(ValueError):
        SURFACE.latency_at(float("nan"), 0)
