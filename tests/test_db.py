from uuid import uuid4
from loguru import logger

import pytest
import sqlmodel
from chat_ui.db import ChatUiDBSession, JobFeedback, FeedbackSuccess, Jobs

from chat_ui import app, get_session
from chat_ui.models import JobStatus, RequestType
from chat_ui.utils import get_waiting_jobs  # noqa: E402

from . import get_test_session  # noqa: E402,F401


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

    userid = uuid4()

    chat_session = ChatUiDBSession(userid=userid)
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)

    # create a job
    job = Jobs(
        client_ip="1.2.3.4",
        status=JobStatus.Created.value,
        userid=str(userid),
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
