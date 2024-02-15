""" This polls the backend to check if it is up and running """

import threading
import time

from loguru import logger
import requests

from chat_ui.config import Config


class BackgroundPoller(threading.Thread):
    def __init__(self, shared_message: str = "run"):
        super().__init__()
        self.config = Config()
        self.shared_message = shared_message

    def run(self) -> None:
        if self.config.backend_url is None:
            logger.error("No backend_url set, not starting background poller")
            return
        logger.debug(
            "Starting background poller on backend_url={}", self.config.backend_url
        )
        loops = 0
        while True:
            # shutdown handler
            if self.shared_message == "stop":
                logger.info("Shutting down background poller")
                break
            loops += 1
            if loops == 5:
                loops = 0
                try:

                    test_url = f"{self.config.backend_url}/models"
                    res = requests.get(test_url, timeout=1)
                    res.raise_for_status()
                    logger.debug("Backend {} is up!", test_url)
                except Exception as error:
                    logger.error(
                        "Failed to query backend test_url={} error={}", test_url, error
                    )
            time.sleep(1)
