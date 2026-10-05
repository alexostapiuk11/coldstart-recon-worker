from placement_measure.pagecache import cached_kib, make_cold, weight_files


def test_cached_reads_the_kernels_figure(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 100 kB\nCached:          123456 kB\n")
    assert cached_kib(str(meminfo)) == 123456
    assert cached_kib(str(tmp_path / "missing")) is None


def test_weight_files_resolve_the_snapshot_symlinks(tmp_path):
    blobs = tmp_path / "hub" / "models--Qwen--Qwen3-4B" / "blobs"
    snap = tmp_path / "hub" / "models--Qwen--Qwen3-4B" / "snapshots" / "rev1"
    blobs.mkdir(parents=True)
    snap.mkdir(parents=True)
    (blobs / "abc").write_text("w")
    (snap / "model-00001-of-00001.safetensors").symlink_to(blobs / "abc")
    (snap / "config.json").write_text("{}")
    assert weight_files(str(tmp_path), "Qwen/Qwen3-4B", "rev1") == [str((blobs / "abc").resolve())]


def test_make_cold_records_both_attempts_and_the_evidence(tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("Cached: 500 kB\n")
    weights = tmp_path / "w.safetensors"
    weights.write_text("w")
    advised = []
    out = make_cold(
        [str(weights)], meminfo=str(meminfo), drop_path=str(tmp_path / "no" / "drop_caches"),
        sync=lambda: None, fadvise=lambda fd, off, n, advice: advised.append(advice),
    )
    drop, fadv = out["attempts"]
    assert not drop["ok"]  # the drop path's directory does not exist, like a read-only /proc/sys
    assert fadv["ok"] and fadv["files"] == 1 and advised
    assert out["cached_kib_before"] == 500
