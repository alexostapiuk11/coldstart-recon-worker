import matplotlib.text
import pytest

from harness.figure_guards import MIN_PHONE_TEXT_PX, PHONE_WIDTH_PX
from harness.store import JsonlStore
from harness.submit import PayloadStubSubmitter
from multilora.analysis import analyse
from multilora.campaign import run
from multilora.conditions import campaign_schedule, gate_schedule
from multilora.figures import FIGURES
from multilora.records import InstanceRecord
from multilora.stub import StubInstanceEndpoint
from tests.conftest import example_prereg

A4 = {
    "gpu_hourly_rate": 1.0,
    "n_models": 20,
    "reference": {"regime": "low-locality", "s": 1.1},
    "rows": [{
        "regime": "low-locality", "s": 1.1,
        "dedicated_cost_per_tenant_month": 730.0,
        "swapped_cost_per_tenant_month": 120.0,
        "sleep_mode_cost_per_tenant_month": None,
    }],
}


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    prereg = example_prereg(include_diagnostic=False, include_control=False)
    tmp = tmp_path_factory.mktemp("fig")
    stores = {}
    for name, schedule in (("campaign", campaign_schedule(prereg)), ("gate", gate_schedule(prereg))):
        store = JsonlStore(tmp / f"{name}.jsonl", InstanceRecord)
        run(schedule, PayloadStubSubmitter(StubInstanceEndpoint(seed=2).run), store, prereg)
        stores[name] = store.read_all()
    return analyse(stores["campaign"], stores["gate"], prereg, a4=A4, iterations=200)


def _rendered_px(fig, size_pt: float) -> float:
    return size_pt * PHONE_WIDTH_PX / (72 * fig.get_size_inches()[0])


@pytest.mark.parametrize("name", sorted(FIGURES))
def test_every_figure_writes_a_file(analysis, tmp_path, name):
    FIGURES[name](analysis, tmp_path / f"{name}.png")
    assert (tmp_path / f"{name}.png").stat().st_size > 10_000


@pytest.mark.parametrize("name", sorted(FIGURES))
def test_every_text_element_is_legible_at_phone_width(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    small = [
        (t.get_text(), round(_rendered_px(fig, t.get_fontsize()), 2))
        for t in fig.findobj(matplotlib.text.Text)
        if t.get_text().strip() and _rendered_px(fig, t.get_fontsize()) < MIN_PHONE_TEXT_PX
    ]
    assert small == []


@pytest.mark.parametrize("name", ["throughput_ttft", "kv_capacity", "equivalence"])
def test_the_instance_count_is_on_the_figure(analysis, tmp_path, name):
    fig = FIGURES[name](analysis, tmp_path / f"{name}.png")
    texts = " ".join(t.get_text() for t in fig.findobj(matplotlib.text.Text))
    assert "n = " in texts


def test_value_axes_start_at_zero(analysis, tmp_path):
    fig = FIGURES["throughput_ttft"](analysis, tmp_path / "a.png")
    assert all(ax.get_ylim()[0] == 0 for ax in fig.axes)
    fig = FIGURES["kv_capacity"](analysis, tmp_path / "b.png")
    assert fig.axes[0].get_ylim()[0] == 0
    fig = FIGURES["cost_per_tenant"](analysis, tmp_path / "c.png")
    assert fig.axes[0].get_xlim()[0] == 0


def test_the_equivalence_band_is_the_pre_registered_margin(analysis, tmp_path):
    fig = FIGURES["equivalence"](analysis, tmp_path / "e.png")
    labels = [t.get_text() for t in fig.findobj(matplotlib.text.Text)]
    assert f"margin ±{100 * analysis['gate']['delta']:.1f}%" in labels


def test_empty_input_is_refused(analysis, tmp_path):
    empty = {**analysis, "sweep": {"points": []}}
    with pytest.raises(ValueError, match="must not be empty"):
        FIGURES["throughput_ttft"](empty, tmp_path / "x.png")


def test_a_sleep_mode_row_gets_its_own_bar(analysis, tmp_path):
    rows = analysis["cost_table"]
    with_sleep = rows[:2] + [{"strategy": "sleep mode", "cost": 60.0, "source": "a4"}] + rows[2:]
    fig = FIGURES["cost_per_tenant"]({**analysis, "cost_table": with_sleep}, tmp_path / "c.png")
    labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert labels == ["dedicated", "swapped", "sleep mode", "adapter"]
