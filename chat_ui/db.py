from datetime import datetime, UTC
from enum import IntEnum

from loguru import logger
from sqlalchemy_utils import UUIDType  # type: ignore

from typing import Any, Optional

from uuid import UUID, uuid4

import sqlmodel
from sqlmodel._compat import SQLModelConfig


from sqlalchemy.exc import NoResultFound
from chat_ui.models import AnalyzeForm, JobStatus, AnalysisType

sqlmodel.SQLModel.__table_args__ = {"extend_existing": True}


class Users(sqlmodel.SQLModel, table=True):
    """database representation of a user"""

    userid: UUID = sqlmodel.Field(primary_key=True, sa_type=UUIDType(binary=False))
    name: str
    created: datetime = datetime.now(UTC)
    updated: Optional[datetime] = None

    model_config = SQLModelConfig(arbitrary_types_allowed=True)


class Jobs(sqlmodel.SQLModel, table=True):
    """database representation of a job"""

    id: UUIDType = sqlmodel.Field(
        primary_key=True, default_factory=uuid4, sa_type=UUIDType(binary=False)
    )
    client_ip: str
    userid: UUID = sqlmodel.Field(
        foreign_key="users.userid", index=True, sa_type=UUIDType(binary=False)
    )
    status: str = sqlmodel.Field(JobStatus.Created.value)
    created: datetime = sqlmodel.Field(datetime.now(UTC))
    updated: Optional[datetime] = None
    prompt: str
    response: Optional[str] = None
    request_type: str
    runtime: Optional[float] = None
    job_metadata: Optional[str] = None

    sessionid: UUID = sqlmodel.Field(
        foreign_key="session.sessionid", sa_type=UUIDType(binary=False)
    )
    model_config = SQLModelConfig(arbitrary_types_allowed=True)

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
            sessionid=backgroundjob.sessionid,
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

    def mark_running(
        self, session: sqlmodel.Session, status: JobStatus = JobStatus.Running
    ) -> None:
        """set in the db that the job is currently running"""
        self.status = status.value
        self.updated = datetime.now(UTC)
        session.add(self)
        session.commit()
        session.refresh(self)

    def mark_error(self, session: sqlmodel.Session, error_message: str) -> None:
        """set the job to error status"""
        self.status = JobStatus.Error.value
        self.response = error_message
        self.updated = datetime.now(UTC)
        session.add(self)
        session.commit()
        session.refresh(self)


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

    id: UUID = sqlmodel.Field(
        primary_key=True, default_factory=uuid4, sa_type=UUIDType(binary=False)
    )
    jobid: UUID = sqlmodel.Field(foreign_key="jobs.id")
    success: int  # See FeedbackSuccess for the values, but it's 1, 0, -1
    comment: str
    src_ip: str
    created: datetime = sqlmodel.Field(datetime.now(UTC))
    model_config = SQLModelConfig(arbitrary_types_allowed=True)

    @classmethod
    def has_feedback(cls, session: sqlmodel.Session, jobid: UUID) -> bool:
        try:
            query = sqlmodel.select(JobFeedback).where(JobFeedback.jobid == jobid)
            session.exec(query).one()
            return True
        except NoResultFound:
            return False

    @classmethod
    def get_feedback(
        cls, session: sqlmodel.Session, jobid: UUID
    ) -> Optional["JobFeedback"]:
        try:
            query = sqlmodel.select(JobFeedback).where(JobFeedback.jobid == jobid)
            return session.exec(query).one()
        except NoResultFound:
            return None


class ChatUiDBSession(sqlmodel.SQLModel, table=True):
    """individual chat session"""

    __tablename__ = "session"

    sessionid: UUID = sqlmodel.Field(primary_key=True, default_factory=lambda: uuid4())
    name: str = sqlmodel.Field(default_factory=lambda: datetime.now(UTC).isoformat())

    userid: UUID = sqlmodel.Field(foreign_key="users.userid")
    created: datetime = sqlmodel.Field(default_factory=lambda: datetime.now(UTC))


class JobAnalysis(sqlmodel.SQLModel, table=True):
    """the analysis of the prompt or response from the LLM"""

    analysisid: UUID = sqlmodel.Field(
        default_factory=lambda: uuid4(),
        primary_key=True,
        sa_type=UUIDType(binary=False),
    )
    jobid: UUID = sqlmodel.Field(
        foreign_key="jobs.id", index=True, sa_type=UUIDType(binary=False)
    )
    userid: UUID = sqlmodel.Field(
        foreign_key="users.userid", index=True, sa_type=UUIDType(binary=False)
    )
    preprompt: str  # what we put in front of the analyzed text
    response: Optional[str] = None
    analysis_type: AnalysisType
    time: datetime = sqlmodel.Field(default_factory=lambda: datetime.now(UTC))
    updated: Optional[datetime] = None
    status: JobStatus = JobStatus.Created
    job_metadata: Optional[str] = None

    def log(self) -> None:
        """log the entry"""
        logger.info(*self.model_dump(mode="json"))

    @classmethod
    def from_analyzeform(cls, analyze_form: AnalyzeForm) -> "JobAnalysis":
        """turn an analyze_form into this"""
        return cls(
            jobid=analyze_form.jobid,
            userid=analyze_form.userid,
            preprompt=analyze_form.preprompt,
            analysis_type=analyze_form.analysis_type,
            response=None,
        )

    def mark_running(
        self, session: sqlmodel.Session, status: JobStatus = JobStatus.Running
    ) -> None:
        """set in the db that the job is currently running"""
        self.status = status
        self._save(session)

    def mark_error(self, session: sqlmodel.Session, error_message: str) -> None:
        """set the job to error status"""
        self.status = JobStatus.Error
        self.response = error_message
        self._save(session)

    def _save(self, session: sqlmodel.Session) -> None:
        self.updated = datetime.now(UTC)
        session.add(self)
        session.commit()
        session.refresh(self)
