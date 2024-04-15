import json
import logging as logging
from typing import Any, Dict


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
