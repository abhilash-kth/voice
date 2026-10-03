"""Entry point for ``python -m app.agents.worker``. The worker CLI boots
from here; importing the package (which this does transitively) performs
all top-level prewarm/bootstrap in the original order."""
import os
import sys
import time

from . import (
    WORKER_AGENT_NAME,
    _worker_load,
    entrypoint,
    prewarm,
    setup_logging,
)

if __name__ == "__main__":
    setup_logging()
    try:
        from app.agents.agent_builder import warm_agent_builder_schemas
        warm_agent_builder_schemas()
    except Exception:
        pass

    from livekit.agents import WorkerOptions, cli

    # livekit-agents v1 ships a Typer CLI that requires a subcommand
    # (start / dev / console). Default to `start` so that
    # `python -m app.agents.worker` boots a production worker out of the box.
    if len(sys.argv) == 1:
        sys.argv.append("start")

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            # Two idle processes so a call that is still winding down cannot
            # block the next one. One stuck job used to make "change agent and
            # call again" look like the worker had silently stopped.
            num_idle_processes=int(os.getenv("NUM_IDLE_PROCESSES", "2")),
            shutdown_process_timeout=float(os.getenv("SHUTDOWN_PROCESS_TIMEOUT", "12")),
            agent_name=WORKER_AGENT_NAME,
            # Windows doesn't support the default "forkserver" context; "spawn"
            # is portable and works on Windows/macOS/Linux alike.
            multiprocessing_context="spawn",
            load_fnc=_worker_load,
            load_threshold=float(os.getenv("WORKER_LOAD_THRESHOLD", "0.95")),
        )
    )
