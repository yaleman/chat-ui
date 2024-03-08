from datetime import datetime
from typing import Annotated, Optional
from uuid import UUID
from pydantic import AfterValidator, BaseModel

from chat_ui.models import validate_request_type, validate_userid


class SessionUpdateForm(BaseModel):
    """when you want to update the name of the chat session"""

    name: str


class NewSessionForm(BaseModel):
    """when you want to ask for a new session"""

    userid: Annotated[str, AfterValidator(validate_userid)]


class NewJobForm(BaseModel):
    """form submitted by a user to create a new job"""

    sessionid: UUID
    userid: UUID
    prompt: str
    request_type: Annotated[str, AfterValidator(validate_request_type)]


class UserForm(BaseModel):
    userid: Annotated[UUID, AfterValidator(validate_userid)]
    name: str


class UserDetail(UserForm):
    """response from the server when you ask/update a user's details"""

    created: datetime
    updated: Optional[datetime] = None
