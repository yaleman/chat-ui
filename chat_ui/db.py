from datetime import datetime, UTC
from enum import IntEnum

from typing import Any, Optional

from uuid import UUID, uuid4

import sqlmodel
from sqlalchemy.exc import NoResultFound
from chat_ui.models import JobStatus


class Users(sqlmodel.SQLModel, table=True):
    """database representation of a user"""

    userid: UUID = sqlmodel.Field(primary_key=True)
    name: str
    created: datetime = datetime.now(UTC)
    updated: Optional[datetime] = None


class Jobs(sqlmodel.SQLModel, table=True):
    """database representation of a job"""

    id: UUID = sqlmodel.Field(primary_key=True, default_factory=uuid4)
    client_ip: str
    userid: UUID = sqlmodel.Field(foreign_key="users.userid", index=True)
    status: str = sqlmodel.Field(JobStatus.Created.value)
    created: datetime = sqlmodel.Field(datetime.now(UTC))
    updated: Optional[datetime] = None
    prompt: str
    response: Optional[str] = None
    request_type: str
    runtime: Optional[float] = None
    job_metadata: Optional[str] = None

    sessionid: UUID = sqlmodel.Field(foreign_key="session.sessionid")

    @classmethod
    def from_backgroundjob(cls, backgroundjob: "BackgroundJob") -> "Jobs":  # type: ignore # noqa: F821
        """create a job from a backgroundjob"""
        return cls(
            id=backgroundjob.id,
            client_ip=backgroundjob.client_ip,
            userid=backgroundjob.userid,
            status=backgroundjob.status,
            created=backgroundjob.created,
            updated=backgroundjob.updated,
            prompt=backgroundjob.prompt,
            response=backgroundjob.response,
            request_type=backgroundjob.request_type,
            runtime=backgroundjob.runtime,
            job_metadata=backgroundjob.job_metadata,
        )

    @classmethod
    def from_newjobform(
        cls, newjobform: Any, client_ip: str, status: JobStatus = JobStatus.Created
    ) -> "Jobs":
        """create a job from a newjobform"""
        return cls(
            status=status.value,
            userid=newjobform.userid,
            prompt=newjobform.prompt,
            client_ip=client_ip,
            request_type=newjobform.request_type,
            sessionid=newjobform.sessionid,
        )


class FeedbackSuccess(IntEnum):
    """feedback success enum"""

    Yes = 1
    No = -1
    Maybe = 0


def validate_feedback_success(v: int) -> int:
    """validates that feedback values are OK"""
    FeedbackSuccess(v)  # this will raise an exception if it's not a valid input
    return v


class JobFeedback(sqlmodel.SQLModel, table=True):
    """database representation of feedback"""

    id: UUID = sqlmodel.Field(primary_key=True, default_factory=uuid4)
    jobid: UUID = sqlmodel.Field(foreign_key="jobs.id")
    success: int  # See FeedbackSuccess for the values, but it's 1, 0, -1
    comment: str
    src_ip: str
    created: datetime = sqlmodel.Field(datetime.now(UTC))

    @classmethod
    def has_feedback(cls, session: sqlmodel.Session, jobid: str) -> bool:
        try:
            query = sqlmodel.select(JobFeedback).where(JobFeedback.jobid == jobid)
            session.exec(query).one()
            return True
        except NoResultFound:
            return False

    @classmethod
    def get_feedback(
        cls, session: sqlmodel.Session, jobid: str
    ) -> Optional["JobFeedback"]:
        try:
            query = sqlmodel.select(JobFeedback).where(JobFeedback.jobid == jobid)
            return session.exec(query).one()
        except NoResultFound:
            return None


class ChatUiDBSession(sqlmodel.SQLModel, table=True):
    """individual chat session"""

    __tablename__ = "session"

    sessionid: str = sqlmodel.Field(
        primary_key=True, default_factory=lambda: str(uuid4())
    )
    name: str = sqlmodel.Field(default_factory=lambda: datetime.now(UTC).isoformat())

    userid: UUID = sqlmodel.Field(foreign_key="users.userid")
    created: datetime = sqlmodel.Field(default_factory=lambda: datetime.now(UTC))
