""" testing appstate """

import os

# from datetime import datetime
# from tempfile import NamedTemporaryFile
from chat_ui import app

from fastapi.testclient import TestClient

from chat_ui.models import UserDetail

os.environ["CHATUI_DB"] = ":memory:"


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


def test_read_main() -> None:
    """tests the thing"""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200


def test_post_user() -> None:
    """tests the thing"""
    from uuid import uuid4

    first_username = "hello world"
    second_username = "Cheesemonkey"
    client = TestClient(app)
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
