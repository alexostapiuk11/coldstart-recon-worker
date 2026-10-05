"""The header names the worker stamps are the names the driver reads.

The middleware (in the worker image) and the driver (on the owner's machine) each
spell the two header names; nothing but this test ties them together. A rename on
one side alone would not crash anything: the driver would see every 200 without a
server-latency header and void all three paid repeats.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "worker"))
sys.path.insert(0, str(REPO / "scripts"))

import a2_lb_common
from a2_middleware import SERVER_LATENCY_HEADER, WORKER_HEADER


def test_the_worker_header_is_the_one_the_driver_reads():
    assert WORKER_HEADER.decode() == a2_lb_common.WORKER


def test_the_server_latency_header_is_the_one_the_driver_reads():
    assert SERVER_LATENCY_HEADER.decode() == a2_lb_common.SERVER_LATENCY
