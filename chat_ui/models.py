from datetime import datetime
from enum import StrEnum
import json
from typing import Annotated, Any, List, Optional, Union
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict


class JobStatus(StrEnum):
    Created = "created"
    Running = "running"
    Error = "error"
    Complete = "complete"
    Hidden = "hidden"


class RequestType(StrEnum):
    DOS = "dos"
    Plain = "plain"
    PromptInjection = "prompt_injection"
    SensitiveDisclosure = "sensitive_disclosure"
    InsecureOutPut = "insecure_output"


def validate_uuid(v: str) -> str:
    """validate a uuidv4"""
    try:
        res = UUID(f"{{{v}}}", version=4)
        assert res.version == 4, "Invalid userid - should be a uuid v4"
    except Exception as error:
        raise ValueError(f"Invalid userid {v} - should be a uuid v4") from error
    return v


def validate_userid(v: str) -> str:
    """validates that the userid is a uuid v4"""
    return validate_uuid(v)


def validate_optional_userid(v: str) -> Optional[str]:
    """validates that the userid is optionally a uuid v4"""
    if v is None:
        return v
    return validate_userid(v)


def validate_job_status(v: str) -> str:
    """validates that job status values are OK"""
    JobStatus(v)  # this will raise an exception if it's not a valid status
    # assert (
    #     v in JOB_STATUSES
    # ), f"Invalid job status {v} - should be one of {', '.join(JOB_STATUSES)}"
    return v


def validate_request_type(v: str) -> str:
    """validates request types"""
    RequestType(v)  # this will raise an exception if it's not a valid status
    return v


class Job(BaseModel):
    id: Annotated[str, AfterValidator(validate_uuid)]
    userid: Annotated[str, AfterValidator(validate_userid)]
    status: Annotated[str, AfterValidator(validate_job_status)]
    created: datetime
    updated: Optional[datetime] = None
    request_type: Annotated[str, AfterValidator(validate_request_type)]

    @classmethod
    def from_jobs(cls, jobs_object: Any) -> "Job":
        newobject = {
            "id": str(jobs_object.id),
            "userid": str(jobs_object.userid),
            "status": jobs_object.status,
            "created": jobs_object.created,
            "updated": jobs_object.updated,
            "request_type": jobs_object.request_type,
        }
        return cls(**newobject)


class JobDetail(Job):
    prompt: str
    response: Optional[str] = None
    runtime: Optional[float] = None
    metadata: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_jobs(cls, jobs_object: Any) -> "JobDetail":
        newobject = {
            "id": str(jobs_object.id),
            "userid": str(jobs_object.userid),
            "status": jobs_object.status,
            "created": jobs_object.created,
            "updated": jobs_object.updated,
            "prompt": jobs_object.prompt,
            "response": jobs_object.response,
            "runtime": jobs_object.runtime,
            "metadata": jobs_object.job_metadata,
            "request_type": jobs_object.request_type,
        }
        return cls(**newobject)


class NewJob(BaseModel):
    userid: Annotated[str, AfterValidator(validate_userid)]
    prompt: str
    request_type: Annotated[str, AfterValidator(validate_request_type)]


class UserForm(BaseModel):
    userid: Annotated[str, AfterValidator(validate_userid)]
    name: str


class UserDetail(UserForm):
    created: datetime
    updated: Optional[datetime] = None


class WebSocketMessageType(StrEnum):
    Jobs = "jobs"
    Delete = "delete"
    Error = "error"
    Resubmit = "resubmit"
    Waiting = "waiting"


def validate_websocket_message(v: str) -> str:
    """validates that job status values are OK"""
    WebSocketMessageType(v)  # this will raise an exception if it's not a valid status
    return v


class WebSocketMessage(BaseModel):
    """things that the client is going to send us across the websocket"""

    userid: Annotated[str, AfterValidator(validate_userid)]
    payload: Optional[str] = None
    message: Annotated[str, AfterValidator(validate_websocket_message)]


class WebSocketResponse(BaseModel):
    """what we send back across the websocket to the client"""

    message: Annotated[str, AfterValidator(validate_websocket_message)]
    payload: Union[List[Job], Job, str]

    def as_message(self) -> str:
        """convert to a string"""
        return json.dumps(self.model_dump(), default=str)


class LogMessages(StrEnum):
    UserUpdate = "user update"
    NewJob = "new job"
    JobDeleted = "job deleted"
    DeleteNotFound = "delete but not found"
    JobMetadata = "job metadata"
    JobCompleted = "job completed"
    JobStarted = "starting job"
    BackgroundPollerShutdown = "Background poller is stopping"
    PendingJobs = "pending jobs"
    Resubmitted = "resubmitted"
    RejectedResubmit = "rejected resubmit due to job status"
    FailedResubmit = "failed resubmit handling"
    NoJobs = "no jobs found"
    WebsocketError = "websocket error"
    JobHistory = "job history"
    CompletionOutput = "completion output"
