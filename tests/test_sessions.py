from uuid import uuid4

from fastapi.testclient import TestClient
import sqlmodel

from chat_ui import app, create_session, get_session
from chat_ui.db import ChatUiDBSession
from chat_ui.enums import Urls
from chat_ui.forms import SessionUpdateForm, UserForm

from . import get_test_session  # noqa: E402,F401


def test_ChatUiDBSession() -> None:
    """test the ChatUiDBSession model"""
    userid = uuid4()
    session = ChatUiDBSession(userid=userid)

    print(session.sessionid)
    assert session.sessionid is not None
    assert session.userid == userid


def test_db_session(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)
    userid = uuid4()
    name = "testuser"

    res = client.post(Urls.User, json={"userid": userid.hex, "name": name})
    assert res.status_code == 200

    res = client.post(f"/session/new/{userid}")

    assert res.status_code == 200
    parse_res: ChatUiDBSession = ChatUiDBSession.model_validate(res.json())

    assert parse_res.userid == userid
    assert parse_res.sessionid is not None
    assert parse_res.created is not None


def test_session_errors(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)

    res = client.post("/session/new/123456")
    assert res.status_code == 422
    res = client.post(f"/session/new/{uuid4()}")
    assert res.status_code == 404


def test_db_get_sessions(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    userid = uuid4()

    res = client.post(
        Urls.User, json=UserForm(userid=userid, name="testuser").model_dump(mode="json")
    )
    assert res.status_code == 200
    create_session(userid, session)
    create_session(userid, session)

    res = client.get(f"{Urls.Sessions}/{userid}")
    assert res.status_code == 200
    parse_res = [ChatUiDBSession.model_validate(x) for x in res.json()]
    assert len(parse_res) == 3

    # tests a missing one
    res = client.get(f"{Urls.Sessions}/{uuid4()}")
    assert res.status_code == 404


def test_update_session(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    userid = uuid4()

    res = client.post(Urls.User, json={"userid": userid.hex, "name": "testuser"})
    assert res.status_code == 200

    res = client.post(f"/session/new/{userid}")

    assert res.status_code == 200
    chatsession = ChatUiDBSession.model_validate(res.json())

    res = client.post(
        f"/session/{userid}/{chatsession.sessionid}",
        json=SessionUpdateForm(name="hello world").model_dump(),
    )
    assert res.status_code == 200

    assert res.json().get("name") == "hello world"

    res = client.post(
        f"/session/{userid}/{uuid4()}",
        json=SessionUpdateForm(name="hello world").model_dump(),
    )
    assert res.status_code == 404
