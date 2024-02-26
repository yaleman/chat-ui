from typing import Union

from fastapi import Request, WebSocket
from openai import AsyncOpenAI

from chat_ui.config import Config


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
