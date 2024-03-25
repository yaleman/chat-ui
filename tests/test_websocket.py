from datetime import UTC, datetime
import json
from uuid import uuid4
from fastapi.testclient import TestClient
import pytest
import sqlmodel
from chat_ui.db import ChatUiDBSession
from chat_ui.forms import NewJobForm

from chat_ui.models import RequestType, WebSocketMessage, WebSocketMessageType

from . import get_test_session  # noqa: E402,F401
from chat_ui import app, get_session
from chat_ui.websocket_handlers import websocket_jobs


@pytest.mark.asyncio()
async def test_websocket_jobs(session: sqlmodel.Session) -> None:
    """test the websocket_jobs function"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)
    userid = uuid4()
    name = "testuser"

    # create a user
    res = client.post("/user", json={"userid": userid.hex, "name": name})
    assert res.status_code == 200

    # create a session
    res = client.post(f"/session/new/{userid}")
    assert res.status_code == 200
    sessionid = ChatUiDBSession.model_validate(res.json()).sessionid

    data = WebSocketMessage(
        userid=userid,
        message=WebSocketMessageType.Jobs,
        payload=json.dumps({"sessionid": sessionid.hex, "since": 0}),
    )
    jobs = await websocket_jobs(data, session, None)  # type: ignore
    assert jobs.message == WebSocketMessageType.Jobs
    assert isinstance(jobs.payload, list)
    assert len(jobs.payload) == 0

    res = client.post(
        "/job",
        json=NewJobForm(
            userid=userid,
            sessionid=sessionid,
            prompt="hello world",
            request_type=RequestType.Plain,
        ).model_dump(mode="json"),
    )

    assert res.status_code == 200

    jobs = await websocket_jobs(data, session, None)  # type: ignore
    assert jobs.message == WebSocketMessageType.Jobs
    assert isinstance(jobs.payload, list)
    assert len(jobs.payload) == 1

    # check for a super-recent time which nothing's been
    data = WebSocketMessage(
        userid=userid,
        message=WebSocketMessageType.Jobs,
        payload=json.dumps(
            {"sessionid": sessionid.hex, "since": datetime.now(UTC).timestamp()}
        ),
    )

    jobs = await websocket_jobs(data, session, None)  # type: ignore
    assert jobs.message == WebSocketMessageType.Jobs
    assert isinstance(jobs.payload, list)
    assert len(jobs.payload) == 0
