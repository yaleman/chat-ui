from typing import Generator
from uuid import uuid4
from loguru import logger

import pytest
import sqlmodel
from chat_ui.db import JobFeedback, FeedbackSuccess, Jobs

from chat_ui import app, get_session
from chat_ui.models import JobStatus, RequestType
from chat_ui.utils import get_waiting_jobs  # noqa: E402


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


def test_jobfeedback(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    jobid = str(uuid4())
    userid = str(uuid4())

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


def test_get_waiting_jobs(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    assert get_waiting_jobs(session)[1] == 0

    # create a job
    job = Jobs(
        client_ip="1.2.3.4",
        status=JobStatus.Created.value,
        userid=str(uuid4()),
        request_type=RequestType.Plain.value,
        prompt="this is a test",
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
