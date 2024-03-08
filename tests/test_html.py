from fastapi.testclient import TestClient
from chat_ui import app


def test_indexpage() -> None:
    client = TestClient(app)

    assert client.get("/").status_code == 200
