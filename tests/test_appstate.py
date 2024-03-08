""" testing appstate """

from uuid import uuid4

# from datetime import datetime, UTC
# from tempfile import NamedTemporaryFile

from fastapi.testclient import TestClient
import sqlmodel
import os
from . import get_test_session  # noqa: E402,F401

from chat_ui.forms import UserDetail, UserForm

os.environ["CHATUI_DB_PATH"] = ":memory:"

from chat_ui import app, get_session  # noqa: E402


def test_read_main() -> None:
    """tests the thing"""

    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200


def test_post_user(session: sqlmodel.Session) -> None:
    """tests the thing"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)

    first_username = "hello world"
    second_username = "Cheesemonkey"
    userid = uuid4()
    response = client.post(
        "/user",
        json=UserForm(userid=userid, name=first_username).model_dump(mode="json"),
    )
    assert response.status_code == 200
    res = UserDetail.model_validate(response.json())
    assert res.userid == userid

    # do a second post to update the record.
    response = client.post(
        "/user",
        json=UserForm(userid=userid, name=second_username).model_dump(mode="json"),
    )
    assert response.status_code == 200
    res = UserDetail.model_validate(response.json())
    assert res.userid == userid
    assert res.updated is not None
    assert res.name != first_username
