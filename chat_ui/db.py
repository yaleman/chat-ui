from datetime import datetime

from typing import Optional
from uuid import UUID, uuid4


import sqlmodel


class Users(sqlmodel.SQLModel, table=True):
    """database representation of a user"""

    userid: UUID = sqlmodel.Field(primary_key=True)
    name: str
    created: datetime = datetime.utcnow()
    updated: Optional[datetime] = None


class Jobs(sqlmodel.SQLModel, table=True):
    """database representation of a job"""

    id: UUID = sqlmodel.Field(primary_key=True, default_factory=uuid4)
    client_ip: str
    userid: UUID = sqlmodel.Field(foreign_key="users.userid")
    status: str
    created: datetime = sqlmodel.Field(datetime.utcnow())
    updated: Optional[datetime] = None
    prompt: str
    response: Optional[str] = None
    request_type: str
    runtime: Optional[float] = None
    job_metadata: Optional[str] = None
