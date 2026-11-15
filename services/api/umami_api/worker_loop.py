"""Worker loop shared by the standalone worker and the API's embedded worker thread."""
import logging
import threading

logger = logging.getLogger("umami.worker")


def tick(database=None) -> str:
    """One iteration. Without a configured database the worker is inert."""
    if database is None:
        return "idle"
    from umami_api.orchestration import dispatch_outbox, run_one
    state = run_one(database)
    dispatch_outbox(database)
    return state


def run_forever(database, stop: threading.Event, poll_seconds: float = 2.0) -> None:
    while not stop.is_set():
        try:
            state = tick(database)
        except Exception:
            logger.exception("worker tick failed")
            state = "error"
        if state in ("idle", "error"):
            stop.wait(poll_seconds)


def start_embedded(database, poll_seconds: float = 2.0) -> tuple[threading.Thread, threading.Event]:
    stop = threading.Event()
    thread = threading.Thread(target=run_forever, args=(database, stop, poll_seconds),
                              name="umami-worker", daemon=True)
    thread.start()
    return thread, stop
