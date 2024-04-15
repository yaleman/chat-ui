import os
from fastapi.testclient import TestClient
from chat_ui import app
from chat_ui.enums import Urls


def filetest(dir: str) -> None:
    client = TestClient(app)
    for filename in os.listdir(f"chat_ui/{dir}"):
        assert client.get(f"/{dir}/{filename}").status_code == 200
        assert client.get(f"/{dir}/{filename}asdfasfasdfasdfsadfsdf").status_code == 404


def test_healthcheck() -> None:
    client = TestClient(app)
    assert client.get(Urls.HealthCheck).status_code == 200


def test_css() -> None:
    """test pulling a file from the /css directory"""
    filetest("css")


def test_img() -> None:
    """test pulling a file from the /img directory"""
    filetest("img")


def test_js() -> None:
    """test pulling a file from the /js directory"""
    filetest("js")
