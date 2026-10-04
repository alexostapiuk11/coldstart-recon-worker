# Superseded: the 1–64 service sweep (2026-10-04)

The first paid campaign, levels 1,2,4,8,16,32,64 × 3 repeats, 21 of 21 runs ok, same
image, template, endpoint, seed and serve args as the campaign in `data/a2/`.

It is superseded, not wrong: the curve had not bent by 64 (throughput still rising
~70–80% per doubling), so 64 would have become the simulator's per-replica cap without
being the engine's limit. The owner chose to re-run the whole campaign at 1–256 into a
new store (`data/a2/service-sweep.jsonl`), because the reducer reads one store and a
level cannot be re-run alone.

Kept as a second measurement of the shared levels: its medians agree with the 1–256
campaign's within about 1% at every level both ran. Nothing reads these files.
