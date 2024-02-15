import os
from uuid import uuid4

import pytest
from chat_ui.models import WebSocketMessage

os.environ["CHATUI_BACKEND_URL"] = "test"


def test_websocketmessage() -> None:
    """test parsing"""
    with pytest.raises(ValueError):
        WebSocketMessage.model_validate({"userid": "foobar", "message": "jobs"})
    with pytest.raises(ValueError):
        WebSocketMessage.model_validate({"userid": str(uuid4()), "message": "test"})
