""" healthcheck script """

import sys

from chat_ui.config import Config
from loguru import logger
import requests

if __name__ == "__main__":
    config = Config()
    res = requests.get(f"{config.backend_url}/models")
    if res.status_code != 200:
        logger.error("Failed to check {}", config.backend_url)
        sys.exit(1)
    sys.exit(0)
