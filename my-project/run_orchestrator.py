import logging
import signal
import sys

import uvicorn

from app import db
from app.health.api import create_app
from app.scheduler import start_scheduler, stop_scheduler, run_all_collectors


HOST = "127.0.0.1"
PORT = 8000


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def main() -> None:
    configure_logging()
    log = logging.getLogger("orchestrator")

    db.init_db()

    start_scheduler()

    app = create_app(trigger_callback=run_all_collectors)

    def _shutdown(signum, _frame):
        log.info("orchestrator: received signal %d, shutting down", signum)
        stop_scheduler()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _shutdown)
        except (ValueError, OSError):
            pass

    log.info("orchestrator: starting FastAPI on http://%s:%d", HOST, PORT)
    try:
        uvicorn.run(app, host=HOST, port=PORT, log_level="info")
    finally:
        stop_scheduler()


if __name__ == "__main__":
    main()
#test