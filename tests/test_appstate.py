""" testing appstate """

from typing import Generator

from uuid import uuid4

# from datetime import datetime
# from tempfile import NamedTemporaryFile

from fastapi.testclient import TestClient
import pytest
import sqlmodel
import os

from chat_ui.models import UserDetail

os.environ["CHATUI_DB_PATH"] = ":memory:"

from chat_ui import app, get_session  # noqa: E402

# def test_appstate_trim() -> None:
#     """tests the history trim thing"""
#     tempfile = NamedTemporaryFile()
#     print(tempfile.name)
#     tempfile.write("{}".encode("utf-8"))
#     tempfile.flush()
#     state = AppState(history_file=tempfile.name, max_history_age=1)

#     state.record_message("test", (datetime.utcnow().timestamp() - 5, "test", "test"))
#     state.trim_history()

#     assert len(state.get_history("test")) == 0


@pytest.fixture(name="session")
def get_test_session() -> Generator[sqlmodel.Session, None, None]:
    """get a session"""
    engine = sqlmodel.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sqlmodel.StaticPool,
    )
    sqlmodel.SQLModel.metadata.create_all(engine)
    with sqlmodel.Session(engine) as session:
        yield session


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
    userid = str(uuid4())
    response = client.post("/user", json={"userid": userid, "name": first_username})
    assert response.status_code == 200
    res = UserDetail.model_validate(response.json())
    assert res.userid == userid

    # do a second post to update the record.
    response = client.post("/user", json={"userid": userid, "name": second_username})
    assert response.status_code == 200
    res = UserDetail.model_validate(response.json())
    assert res.userid == userid
    assert res.updated is not None
    assert res.name != first_username
