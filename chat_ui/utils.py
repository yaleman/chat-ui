from datetime import datetime
from functools import lru_cache
from typing import Tuple, Union

from fastapi import Request, WebSocket
from loguru import logger
from openai import AsyncOpenAI
from sqlmodel import Session, or_

from chat_ui.config import Config
from chat_ui.db import Jobs


def get_client_ip(request: Union[Request, WebSocket]) -> str:
    """gets the client IP and falls back to 'unknown' if it can't"""
    client_ip = "unknown"
    if hasattr(request, "client"):
        if request.client is not None:
            client_ip = request.client.host
    return client_ip


def get_backend_client() -> AsyncOpenAI:
    """returns the backend client"""
    return AsyncOpenAI(
        api_key=Config().backend_api_key,
        base_url=Config().backend_url,
    )


@lru_cache(maxsize=2)
def get_waiting_jobs(session: Session) -> Tuple[datetime, int]:
    try:
        res = (
            session.query(Jobs)
            .where(or_(Jobs.status == "created", Jobs.status == "running"))
            .count()
        )
        logger.info("pending jobs", pending_jobs=res)
        return (datetime.utcnow(), res)
    except Exception as error:
        logger.error("Failed to get waiting count", error=error)
        return (datetime.utcnow(), 0)
