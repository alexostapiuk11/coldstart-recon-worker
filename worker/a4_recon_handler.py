"""Artifact 4's reconnaissance handler. Captures; publishes nothing.

Selected by overriding the template's dockerStartCmd with
`python3 -u /opt/a4_recon_handler.py`. One probe per job; see
placement_measure/recon.py for what each answers.
"""

from placement_measure.recon import run_probe


def handler(job):
    return run_probe(job.get("input") or {})


def main():
    # Imported here so tests can import the handler without the runpod SDK.
    import runpod

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
