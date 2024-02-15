from datetime import datetime
import json
from typing import Annotated, List, Optional, Union
from uuid import UUID
from pydantic import AfterValidator, BaseModel, ConfigDict


JOB_STATUSES = ["created", "running", "error", "complete", "hidden"]
REQUEST_TYPES = [
    "plain",
    "prompt_injection",
    "sensitive_disclosure",
    "insecure_output",
]


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
    assert (
        v in JOB_STATUSES
    ), f"Invalid job status {v} - should be one of {', '.join(JOB_STATUSES)}"
    return v


def validate_request_type(v: str) -> str:
    """validates request types"""
    assert (
        v in REQUEST_TYPES
    ), f"Invalid request type {v} - should be one of {', '.join(REQUEST_TYPES)}"
    return v


class Job(BaseModel):
    id: Annotated[str, AfterValidator(validate_uuid)]
    userid: Annotated[str, AfterValidator(validate_userid)]
    status: Annotated[str, AfterValidator(validate_job_status)]
    created: datetime
    updated: Optional[datetime] = None


class JobDetail(Job):
    prompt: str
    response: Optional[str] = None
    runtime: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


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


WEBSOCKET_MESSAGES = ["jobs", "delete", "error"]


def validate_websocket_message(v: str) -> str:
    """validates that job status values are OK"""
    assert (
        v in WEBSOCKET_MESSAGES
    ), f"Invalid websocket message {v} - should be one of {', '.join(WEBSOCKET_MESSAGES)}"
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
