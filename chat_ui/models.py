from datetime import datetime
from enum import StrEnum
import json
from typing import Annotated, Any, List, Optional, Union
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict
from sqlmodel import SQLModel


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
    InsecureOutput = "insecure_output"


class WebSocketMessageType(StrEnum):
    Jobs = "jobs"
    Delete = "delete"
    Error = "error"
    Resubmit = "resubmit"
    Feedback = "feedback"
    Waiting = "waiting"
    NewChat = "newchat"


def validate_uuid(v: Union[str, UUID]) -> Union[str, UUID]:
    """validate a uuidv4"""
    if isinstance(v, UUID):
        return v
    try:
        res = UUID(f"{{{v}}}", version=4)
        assert res.version == 4, "Invalid userid - should be a uuid v4"
    except Exception as error:
        raise ValueError(f"Invalid userid {v} - should be a uuid v4") from error
    return v


def validate_userid(v: str | UUID) -> Union[str, UUID]:
    """validates that the userid is a uuid v4"""
    return validate_uuid(v)


def validate_optional_userid(v: Union[str, UUID]) -> Optional[Union[str, UUID]]:
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
    id: Annotated[UUID, AfterValidator(validate_uuid)]
    status: Annotated[str, AfterValidator(validate_job_status)]
    created: datetime
    updated: Optional[datetime] = None
    # request_type: Annotated[str, AfterValidator(validate_request_type)]
    sessionid: UUID

    @classmethod
    def from_jobs(
        cls,
        jobs_object: Any,
        jobsfeedback: Optional[SQLModel],
    ) -> "Job":
        newobject = {
            "id": jobs_object.id.hex,
            "status": jobs_object.status,
            "created": jobs_object.created,
            "updated": jobs_object.updated,
            # "request_type": jobs_object.request_type,
            "sessionid": jobs_object.sessionid,
        }
        return cls(**newobject)


class JobDetail(Job):
    prompt: str
    sessionid: UUID

    response: Optional[str] = None
    runtime: Optional[float] = None
    metadata: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    # if they've supplied feedback
    feedback_comment: Optional[str] = None
    feedback_success: Optional[int] = None

    @classmethod
    def from_jobs(
        cls,
        jobs_object: Any,
        jobsfeedback: Optional[Any],
    ) -> "JobDetail":
        newobject = {
            "id": jobs_object.id.hex,
            "userid": jobs_object.userid.hex,
            "status": jobs_object.status,
            "created": jobs_object.created,
            "updated": jobs_object.updated,
            "prompt": jobs_object.prompt,
            "response": jobs_object.response,
            "runtime": jobs_object.runtime,
            "metadata": jobs_object.job_metadata,
            "request_type": jobs_object.request_type,
            "sessionid": jobs_object.sessionid,
        }
        if jobsfeedback is not None:
            newobject["feedback_comment"] = jobsfeedback.comment
            newobject["feedback_success"] = jobsfeedback.success
        return cls(**newobject)


def validate_websocket_message(v: str) -> str:
    """validates that job status values are OK"""
    WebSocketMessageType(v)  # this will raise an exception if it's not a valid status
    return v


class WebSocketMessage(BaseModel):
    """things that the client is going to send us across the websocket"""

    userid: Annotated[UUID, AfterValidator(validate_userid)]
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
    AnalysisJobMetadata = "analysis job metadata"
    AnalysisJobStarting = "analysis job starting"
    AnalysisJobCompletionOutput = "analysis completion output"
    BackgroundPollerShutdown = "Background poller is stopping"
    DeleteNotFound = "delete but not found"
    JobCompleted = "job completed"
    JobCompletionOutput = "completion output"
    JobDeleted = "job deleted"
    JobFeedback = "job feedback"
    JobHistory = "job history"
    JobMetadata = "job metadata"
    JobNew = "new job"
    JobStarted = "starting job"
    NoJobs = "no jobs found"
    PendingJobs = "pending jobs"
    RejectedResubmit = "rejected resubmit due to job status"
    ResubmitFailed = "failed resubmit handling"
    Resubmitted = "resubmitted"
    SessionNew = "new session"
    SessionUpdate = "session updated"
    UserUpdate = "user update"
    WebsocketError = "websocket error"
    WebsocketDisconnected = "websocket disconnected"


class AnalysisType(StrEnum):
    """used when pushing the prompt or response back through the LLM"""

    Prompt = "prompt"
    Response = "response"
    PromptAndResponse = "prompt_and_response"


class AnalyzeForm(BaseModel):
    """form submitted for analysis of a prompt / response"""

    jobid: Annotated[UUID, AfterValidator(validate_userid)]
    userid: Annotated[UUID, AfterValidator(validate_userid)]

    analysis_type: AnalysisType
    # the thing we put in front of the prompt
    preprompt: str
