import os
from uuid import uuid4

import pytest
from chat_ui.models import JobStatus, RequestType, WebSocketMessage

os.environ["CHATUI_BACKEND_URL"] = "test"


def test_websocketmessage() -> None:
    """test parsing"""
    with pytest.raises(ValueError):
        WebSocketMessage.model_validate({"userid": "foobar", "message": "jobs"})
    with pytest.raises(ValueError):
        WebSocketMessage.model_validate({"userid": str(uuid4()), "message": "test"})


def test_jobstatus() -> None:
    with pytest.raises(ValueError):
        JobStatus("foobar")
    JobStatus("created")


def test_requestype() -> None:
    with pytest.raises(ValueError):
        RequestType("foobar")
    RequestType("plain")
