import os
from uuid import uuid4

import sqlmodel
import pytest
from fastapi.testclient import TestClient
from chat_ui import app, get_session
from chat_ui.enums import Urls


# this sets up the fixture for the session
from . import get_test_session  # noqa: E402,F401


@pytest.mark.asyncio()
async def test_admin_jobs(session: sqlmodel.Session) -> None:
    """tests the admin jobs functionality"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)

    response = client.get(Urls.AdminJobs)
    assert response.status_code == 422

    if os.getenv("CHATUI_ADMIN_PASSWORD") is None:
        temp_admin_password = "admin12345"
        os.environ["CHATUI_ADMIN_PASSWORD"] = temp_admin_password
    else:
        temp_admin_password = os.getenv("CHATUI_ADMIN_PASSWORD") or ""

    response = client.get(Urls.AdminJobs, headers={"admin-password": uuid4().hex})
    print(response.text)
    assert response.status_code == 403

    response = client.get(Urls.AdminJobs, headers={"admin-password": temp_admin_password})
    print(response.text)
    assert response.status_code == 200

    response = client.get(
        Urls.AdminJobs,
        headers={"admin-password": temp_admin_password},
        params={"userid": uuid4().hex, "sessionid": uuid4().hex},
    )

    # remove the password and test it again
    del os.environ["CHATUI_ADMIN_PASSWORD"]

    response = client.get(Urls.AdminJobs, headers={"admin-password": temp_admin_password})
    print(response.text)
    assert response.status_code == 500

    os.environ["CHATUI_ADMIN_PASSWORD"] = temp_admin_password


def test_admin_users() -> None:
    """tests the admin users functionality"""

    client = TestClient(app)

    response = client.get(Urls.AdminUsers)
    assert response.status_code == 422

    if os.getenv("CHATUI_ADMIN_PASSWORD") is None:
        temp_admin_password = "admin12345"
        os.environ["CHATUI_ADMIN_PASSWORD"] = temp_admin_password
    else:
        temp_admin_password = os.getenv("CHATUI_ADMIN_PASSWORD") or ""

    response = client.get(Urls.AdminUsers, headers={"admin-password": uuid4().hex})
    print(response.text)
    assert response.status_code == 403

    response = client.get(Urls.AdminUsers, headers={"admin-password": temp_admin_password})
    print(response.text)
    assert response.status_code == 200

    response = client.get(
        Urls.AdminUsers,
        headers={"admin-password": temp_admin_password},
        params={"userid": uuid4().hex},
    )

    # remove the password and test it again
    del os.environ["CHATUI_ADMIN_PASSWORD"]

    response = client.get(Urls.AdminUsers, headers={"admin-password": temp_admin_password})
    print(response.text)
    assert response.status_code == 500

    os.environ["CHATUI_ADMIN_PASSWORD"] = temp_admin_password


def test_admin_analyses() -> None:
    """tests the admin analyses functionality"""

    client = TestClient(app)

    response = client.get(Urls.AdminAnalyses)
    assert response.status_code == 422

    if os.getenv("CHATUI_ADMIN_PASSWORD") is None:
        temp_admin_password = "admin12345"
        os.environ["CHATUI_ADMIN_PASSWORD"] = temp_admin_password
    else:
        temp_admin_password = os.getenv("CHATUI_ADMIN_PASSWORD") or ""

    response = client.get(Urls.AdminAnalyses, headers={"admin-password": uuid4().hex})
    print(response.text)
    assert response.status_code == 403

    response = client.get(Urls.AdminAnalyses, headers={"admin-password": temp_admin_password})
    print(response.text)
    assert response.status_code == 200

    response = client.get(
        Urls.AdminAnalyses,
        headers={"admin-password": temp_admin_password},
        params={"userid": uuid4().hex, "analysisid": uuid4().hex},
    )

    # remove the password and test it again
    del os.environ["CHATUI_ADMIN_PASSWORD"]

    response = client.get(Urls.AdminAnalyses, headers={"admin-password": temp_admin_password})
    print(response.text)
    assert response.status_code == 500

    os.environ["CHATUI_ADMIN_PASSWORD"] = temp_admin_password


def test_admin_sessions() -> None:
    """tests the admin sessions functionality"""

    client = TestClient(app)

    response = client.get(Urls.AdminSessions)
    assert response.status_code == 422

    if os.getenv("CHATUI_ADMIN_PASSWORD") is None:
        temp_admin_password = "admin12345"
        os.environ["CHATUI_ADMIN_PASSWORD"] = temp_admin_password
    else:
        temp_admin_password = os.getenv("CHATUI_ADMIN_PASSWORD") or ""

    response = client.get(Urls.AdminSessions, headers={"admin-password": uuid4().hex})
    print(response.text)
    assert response.status_code == 403

    response = client.get(Urls.AdminSessions, headers={"admin-password": temp_admin_password})
    print(response.text)
    assert response.status_code == 200

    response = client.get(
        Urls.AdminSessions,
        headers={"admin-password": temp_admin_password},
        params={"userid": uuid4().hex},
    )

    # remove the password and test it again
    del os.environ["CHATUI_ADMIN_PASSWORD"]

    response = client.get(Urls.AdminSessions, headers={"admin-password": temp_admin_password})
    print(response.text)
    assert response.status_code == 500

    os.environ["CHATUI_ADMIN_PASSWORD"] = temp_admin_password
