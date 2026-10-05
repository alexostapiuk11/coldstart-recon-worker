"""Artifact 4's measurement handler: one swap or one co-location cell per job.

Selected by overriding the template's dockerStartCmd with
`python3 -u /opt/a4_measure_handler.py`. See placement_measure/jobs.py.
"""

from placement_measure.jobs import measure_job


def handler(job):
    return measure_job(job.get("input") or {})


def main():
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
