""" testing appstate """

from datetime import datetime
from tempfile import NamedTemporaryFile
from chat_ui import AppState, app

from fastapi.testclient import TestClient

def test_appstate_trim() -> None:
    """ tests the history trim thing """
    tempfile = NamedTemporaryFile()
    print(tempfile.name)
    tempfile.write("{}".encode('utf-8'))
    tempfile.flush()
    state = AppState(history_file=tempfile.name, max_history_age=1)

    state.record_message("test", (datetime.utcnow().timestamp()-5, "test", "test"))
    state.trim_history()

    assert len(state.get_history("test")) == 0




def test_read_main() -> None:
    """ tests the thing """
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200