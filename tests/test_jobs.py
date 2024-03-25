from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import sqlmodel

from chat_ui import app, get_session
from chat_ui.db import ChatUiDBSession
from chat_ui.forms import NewJobForm
from chat_ui.models import RequestType

from . import get_test_session  # noqa: E402,F401


def test_jobs(session: sqlmodel.Session) -> None:
    """test getting jobs from the /jobs endpoint"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)
    userid = uuid4()
    name = "testuser"

    res = client.post("/user", json={"userid": userid.hex, "name": name})
    assert res.status_code == 200

    res = client.post(f"/session/new/{userid}")
    assert res.status_code == 200

    sessionid = ChatUiDBSession.model_validate(res.json()).sessionid

    # no userid? throw an error
    res = client.get("/jobs?userid=")
    assert res.status_code == 422
    # wrong userid? throw an error
    res = client.get("/jobs?userid=asdfasdf")
    assert res.status_code == 422
    # invalid userid? empty
    res = client.get(f"/jobs?userid={uuid4()}")
    assert res.status_code == 200
    assert res.json() == []

    # check we're getting nothing back
    res = client.get(f"/jobs?userid={userid}")
    assert res.status_code == 200
    assert res.json() == []

    # create a job
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

    # check we're getting something back now
    res = client.get(f"/jobs?userid={userid}")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert UUID(res.json()[0]["sessionid"]) == sessionid

    res = client.get(f"/jobs?userid={userid}&since=0")
    assert res.status_code == 200
    assert len(res.json()) == 1

    now = datetime.now(UTC).timestamp()
    res = client.get(f"/jobs?userid={userid}&since={now}")
    assert res.status_code == 200
    assert len(res.json()) == 0
