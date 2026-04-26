"""Process entrypoint: spawn ingester thread + retention thread + uvicorn."""
from __future__ import annotations

import logging
import signal
import threading

import uvicorn

from . import config
from .api.app import create_app
from .ingester import Ingester
from . import indexing_db
from .retention import Retention

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    # Bootstrap indexing DB schema and reap stale jobs from previous runs
    indexing_db.init_schema()
    conn = indexing_db.open_and_bootstrap()
    indexing_db.reap_stale(conn)
    conn.close()

    stop_event = threading.Event()

    ingester = Ingester(stop_event=stop_event)
    retention = Retention(stop_event=stop_event)

    ingester_thread = threading.Thread(target=ingester.run_forever, name="ingester", daemon=True)
    retention_thread = threading.Thread(target=retention.run_forever, name="retention", daemon=True)
    ingester_thread.start()
    retention_thread.start()

    def _shutdown(signum, _frame):
        log.info("Signal %s received; initiating graceful shutdown", signum)
        stop_event.set()
        ingester_thread.join(timeout=config.SHUTDOWN_GRACE_S)
        retention_thread.join(timeout=config.SHUTDOWN_GRACE_S)
        ingester.close()
        retention.close()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    app = create_app()
    uvicorn.run(
        app,
        host=config.SP_COCKPIT_HOST,
        port=config.SP_COCKPIT_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
