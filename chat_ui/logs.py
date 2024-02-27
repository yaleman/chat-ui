import json
import logging as logging
from typing import Any, Dict
from loguru import logger


def serialize(record: Dict[str, Any]) -> str:
    """serializes the loguru record"""
    level = record["level"].name
    subset = {
        "timestamp": record["time"].timestamp(),
        "message": record["message"],
        "level": level,
        "logger": record["name"],
    }
    if level != "INFO":
        subset["line"] = record["line"]
        subset["module"] = record["module"]
        subset["function"] = record["function"]

    for key, value in record["extra"].items():
        subset[key] = value
    # print(f"original: {json.dumps(record, indent=2, default=str)}")
    return json.dumps(subset, default=str, ensure_ascii=False)


def sink(message: Any) -> None:
    serialized = serialize(message.record)
    print(serialized)


class InterceptHandler(logging.Handler):
    """
    Default handler from examples in loguru documentaion.
    See https://loguru.readthedocs.io/en/stable/overview.html#entirely-compatible-with-standard-logging
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding Loguru level if it exists
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = logging.getLevelName(record.levelno)

        # Find caller from where originated the logged message
        frame, depth = logging.currentframe(), 2
        while frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )
