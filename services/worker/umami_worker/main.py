"""Standalone background worker: ``PYTHONPATH=services/api:services/worker python -m umami_worker.main``.

Executes durable jobs and dispatches the transactional outbox (UA-009). It never
contacts or submits to laboratories: only reviewed, non-physical job handlers exist.
The API can run the same loop in-process with EMBEDDED_WORKER=true.
"""
import logging
import os
import threading
import time

from umami_api.worker_loop import run_forever, tick

logger = logging.getLogger(__name__)
__all__ = ["main", "tick"]


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    from umami_api.config import load_settings
    settings = load_settings()
    logger.info("Umami worker started; laboratory submissions are disabled")
    if not settings.database_url:
        while True:
            tick()
            time.sleep(float(os.getenv("WORKER_POLL_SECONDS", "30")))
    from umami_api.db import Database
    run_forever(Database(settings.database_url), threading.Event(),
                float(os.getenv("WORKER_POLL_SECONDS", "2")))


if __name__ == "__main__":
    main()
