"""Placeholder worker process with JSON heartbeat logs (CHT worker pattern)."""

from __future__ import annotations

import time

from utils.logger import setup_logger

logger = setup_logger("contenthub.worker")

HEARTBEAT_SEC = 600


def main() -> None:
    logger.info("contenthub-worker placeholder started", extra={"heartbeat_sec": HEARTBEAT_SEC})
    while True:
        time.sleep(HEARTBEAT_SEC)
        logger.info(
            "poll heartbeat - idle, consumer alive",
            extra={"component": "contenthub-worker", "status": "idle"},
        )


if __name__ == "__main__":
    main()
