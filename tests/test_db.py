from uuid import uuid4
from fastapi.testclient import TestClient
from loguru import logger

import pytest
import sqlmodel
from chat_ui.db import (
    ChatUiDBSession,
    JobFeedback,
    FeedbackSuccess,
    Jobs,
    migrate_database,
)

from chat_ui import app, get_session, startup_check_outstanding_jobs, user_has_sessions
from chat_ui.enums import Urls
from chat_ui.forms import UserForm
from chat_ui.models import JobStatus, RequestType
from chat_ui.utils import get_waiting_jobs  # noqa: E402

from . import get_test_session  # noqa: E402,F401


def test_jobfeedback(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    jobid = uuid4()
    userid = uuid4()

    assert JobFeedback.has_feedback(session, jobid) is False

    feedback = JobFeedback(
        success=FeedbackSuccess.Yes,
        comment="this is a test",
        userid=userid,
        jobid=jobid,
        src_ip="1.2.3.4",
    )
    session.add(feedback)
    session.commit()
    session.refresh(feedback)

    assert JobFeedback.has_feedback(session, jobid)


def test_user_has_sessions(session: sqlmodel.Session) -> None:
    userid = uuid4()

    user_has_sessions(userid=userid, session=session)

    client = TestClient(app)
    # create a user
    response = client.post(
        Urls.User, json=UserForm(userid=userid, name="foo").model_dump(mode="json")
    )
    assert response.status_code == 200

    assert user_has_sessions(userid=userid, session=session) == 0
    chat_session = ChatUiDBSession(userid=userid)
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    assert user_has_sessions(userid=userid, session=session) == 1


def test_get_waiting_jobs(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    assert get_waiting_jobs(session)[1] == 0

    userid = uuid4()

    user_has_sessions(userid=userid, session=session)

    chat_session = ChatUiDBSession(userid=userid)
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)

    # create a job
    job = Jobs(
        client_ip="1.2.3.4",
        status=JobStatus.Created.value,
        userid=userid,
        request_type=RequestType.Plain.value,
        prompt="this is a test",
        sessionid=chat_session.sessionid,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    logger.info(job)

    # have to force the lru cache expiry
    get_waiting_jobs.cache_clear()
    assert get_waiting_jobs(session)[1] == 1

    job.status = JobStatus.Complete.value
    session.commit()

    # have to force the lru cache expiry
    get_waiting_jobs.cache_clear()
    assert get_waiting_jobs(session)[1] == 0


def test_success_enum() -> None:
    with pytest.raises(ValueError):
        FeedbackSuccess(23)
    FeedbackSuccess(1)
    FeedbackSuccess(0)
    FeedbackSuccess(-1)


def test_migrate_database() -> None:

    sqlite_url = "sqlite://"
    engine = sqlmodel.create_engine(
        sqlite_url, echo=False, connect_args={"check_same_thread": False}
    )

    sqlmodel.SQLModel.metadata.create_all(engine)
    migrate_database(engine)
    startup_check_outstanding_jobs(engine)
