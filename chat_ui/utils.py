from datetime import datetime, UTC
from functools import lru_cache
from typing import Tuple, Union

from fastapi import Request, WebSocket
from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import func
from sqlalchemy.exc import NoResultFound
from sqlmodel import Session, or_, select
import cmarkgfm  # type: ignore
import cmarkgfm.cmark  # type: ignore

from chat_ui.config import Config
from chat_ui.db import Jobs
from chat_ui.models import JobStatus, LogMessages


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
        query = select(func.count(Jobs.id)).where(  # type: ignore
            or_(
                Jobs.status == JobStatus.Created.value,
                Jobs.status == JobStatus.Running.value,
            )
        )

        # logger.debug("get_waiting jobs query: {}", query.params())
        res = session.scalar(query)
        if res is None:
            res = 0

        logger.info(LogMessages.PendingJobs, pending_jobs=res)
        return (datetime.now(UTC), res)
    except NoResultFound:
        return (datetime.now(UTC), 0)
    except Exception as error:
        logger.error("Failed to get waiting count", error=error)
        return (datetime.now(UTC), 0)


def html_from_response(input: str) -> str:
    """turn a markdown/HTML response into a HTML string"""

    # documentation here: <https://github.com/theacodes/cmarkgfm?tab=readme-ov-file#advanced-usage>
    if input is None:
        return ""
    try:
        options = cmarkgfm.cmark.Options.CMARK_OPT_VALIDATE_UTF8
        res: str = cmarkgfm.github_flavored_markdown_to_html(input, options=options)
        return res
    except Exception as error:
        logger.error(
            "Failed to convert markdown to HTML, returning raw input", error=error
        )
        return input
