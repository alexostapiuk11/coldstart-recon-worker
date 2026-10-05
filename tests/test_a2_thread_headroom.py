"""The replay's thread pool stays under the OS's per-process thread limit.

Repeat 1 (2026-10-05) died with "can't start new thread": the pool's cap was
4096, macOS allows 4096 threads per process, and the main thread is one of them.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import a2_lb_common as common
import a2_lb_probe as probe
import a2_validate as v


def test_the_pool_leaves_headroom_under_macos_thread_limit():
    assert common.POOL_THREADS + common.THREAD_HEADROOM <= 4096


def test_the_probe_and_the_driver_use_the_shared_cap():
    assert probe.LADDER_MAX_IN_FLIGHT == common.POOL_THREADS
    assert v.REPLAY_MAX_IN_FLIGHT == common.POOL_THREADS


def test_enough_threads_passes_and_too_few_is_refused_naming_the_limit():
    common.ensure_thread_headroom(limit_fn=lambda: 4096)
    with pytest.raises(SystemExit, match="kern.num_taskthreads"):
        common.ensure_thread_headroom(limit_fn=lambda: common.POOL_THREADS)


def test_an_unknown_limit_is_not_refused():
    """Off macOS there is no sysctl to read; the fd check still applies."""
    common.ensure_thread_headroom(limit_fn=lambda: None)


def test_the_limit_is_read_on_this_machine():
    if sys.platform != "darwin":
        pytest.skip("macOS only")
    assert common.macos_thread_limit() >= 1024
