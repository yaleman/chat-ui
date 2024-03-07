""" This polls the backend to check if it is up and running """

import asyncio
from datetime import datetime
import json
import threading
import time
from typing import List, Optional, Tuple, Union
from uuid import UUID, uuid4

from loguru import logger
from pydantic import BaseModel, Field

from sqlmodel import Session, select

from sqlalchemy import Engine
from sqlalchemy.exc import NoResultFound
from chat_ui.config import Config
from chat_ui.db import Jobs
from chat_ui.models import JobStatus, LogMessages
from chat_ui.utils import get_backend_client


from openai.types.chat import (
    ChatCompletionUserMessageParam,
    ChatCompletionAssistantMessageParam,
)


class BackgroundJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    client_ip: str
    userid: UUID
    status: str
    created: datetime = Field(datetime.utcnow())
    updated: Optional[datetime] = None
    prompt: str
    response: Optional[str] = None
    request_type: str
    runtime: Optional[float] = None
    job_metadata: Optional[str] = None
    history: List[Jobs] = []

    @classmethod
    def from_jobs(cls, job: Jobs) -> "BackgroundJob":
        return cls(
            id=job.id,
            client_ip=job.client_ip,
            userid=job.userid,
            status=job.status,
            created=job.created,
            updated=job.updated,
            prompt=job.prompt,
            response=job.response,
            request_type=job.request_type,
            runtime=job.runtime,
            job_metadata=job.job_metadata,
        )

    def get_history(
        self,
    ) -> List[
        Union[
            # ChatCompletionSystemMessageParam,
            ChatCompletionUserMessageParam,
            ChatCompletionAssistantMessageParam,
            # ChatCompletionToolMessageParam,
            # ChatCompletionFunctionMessageParam,
        ]
    ]:

        history: List[
            Union[
                # ChatCompletionSystemMessageParam,
                ChatCompletionUserMessageParam,
                ChatCompletionAssistantMessageParam,
                # ChatCompletionToolMessageParam,
                # ChatCompletionFunctionMessageParam,
            ]
        ] = []

        for job in self.history:
            history.append(
                ChatCompletionUserMessageParam(content=job.prompt, role="user")
            )
            if job.response is not None and job.response.strip():
                history.append(
                    ChatCompletionAssistantMessageParam(
                        content=job.response, role="assistant"
                    )
                )
        history.append(ChatCompletionUserMessageParam(content=self.prompt, role="user"))
        return history


def rough_history_tokens(
    history: List[Jobs],
) -> List[Tuple[str, int]]:
    """roughly calculate the token count based on the history, takes the number of words in the prompt and response and multiplies by 4 to get a rough token count."""
    tokens = []
    for job in history:
        this_words = len(job.prompt.split())
        if job.response is not None:
            this_words += len(job.response.split())
        tokens += [
            (
                str(job.id),
                this_words * 4,
            )
        ]
    return tokens


def sort_by_updated_or_created(objects: List[Jobs]) -> List[Jobs]:
    """sort a list of jobs by the updated or created field, if updated is not set, use created."""

    def get_sort_key(self: Jobs) -> datetime:
        """returns the sorting key for the object"""
        if self.updated is not None:
            return self.updated
        return self.created

    return sorted(objects, key=get_sort_key)


class BackgroundPoller(threading.Thread):
    def __init__(self, engine: Engine):
        super().__init__()
        self.config = Config()
        self.message = "run"
        self.engine = engine
        self.event_loop = asyncio.new_event_loop()

    async def handle_job(self, job: BackgroundJob) -> Jobs:

        start_time = datetime.utcnow().timestamp()
        client = get_backend_client()
        # we need to make sure we're under the token limit

        history_tokens = rough_history_tokens(job.history)
        total_history_tokens = sum([t[1] for t in history_tokens])
        while total_history_tokens > 2048:
            job.history.pop(0)
            history_tokens = rough_history_tokens(job.history)
            total_history_tokens = sum([t[1] for t in history_tokens])
        history = job.get_history()

        logger.debug(
            LogMessages.JobHistory,
            userid=job.userid,
            id=job.id,
            history=history,
            history_length=len([]),
            history_tokens=history_tokens,
            total_history_tokens=total_history_tokens,
        )

        completion = await client.chat.completions.create(
            model="gpt-3.5-turbo",  # this field is currently unused
            messages=history,
            temperature=0.7,
            stream=False,
        )

        logger.debug(
            LogMessages.CompletionOutput,
            userid=job.userid,
            job_id=job.id,
            **completion.model_dump(),
        )
        if completion.usage is not None:
            usage = completion.usage.model_dump()
        else:
            usage = {}

        job.runtime = datetime.utcnow().timestamp() - start_time
        job.response = completion.choices[0].message.content
        job.job_metadata = json.dumps(
            {
                "model": completion.model,
                "usage": usage,
            },
            default=str,
        )

        # so it's slightly easier to parse in the logs
        logger.info(
            LogMessages.JobMetadata,
            job_id=job.id,
            userid=job.userid,
            **usage,
        )

        job.status = JobStatus.Complete.value
        logger.info(LogMessages.JobCompleted, **job.model_dump(exclude={"history"}))
        return Jobs.from_backgroundjob(job)

    def run(self) -> None:
        while self.message == "run":
            with Session(self.engine) as session:
                try:
                    job = session.exec(
                        select(Jobs).where(Jobs.status == JobStatus.Created.value)
                    ).first()
                    if job is None:
                        time.sleep(0.1)
                        continue
                    job.status = JobStatus.Running.value
                    job.updated = datetime.utcnow()
                    session.add(job)
                    session.commit()
                    session.refresh(job)

                    backgroundjob = BackgroundJob.from_jobs(job)
                    query = select(Jobs).where(
                        Jobs.userid == backgroundjob.userid,
                        Jobs.status == JobStatus.Complete.value,
                    )
                    try:
                        # TODO: sort the history by "created" field

                        backgroundjob.history = [
                            job for job in session.exec(query).all()
                        ]

                    except Exception as error:
                        logger.error(
                            "failed to pull history",
                            error=error,
                            userid=job.userid,
                            id=job.id,
                        )

                    try:
                        start_log_entry = {**backgroundjob.model_dump()}
                        history = start_log_entry.pop(
                            "history"
                        )  # need to strip this off because it's just huge
                        logger.debug(
                            "job history", id=job.id, userid=job.userid, history=history
                        )

                        logger.info(LogMessages.JobStarted, **start_log_entry)
                        background_job_result = self.event_loop.run_until_complete(
                            self.handle_job(backgroundjob)
                        )
                        job.updated = datetime.utcnow()
                        background_job_result.model_dump(
                            exclude_unset=False, exclude_none=False
                        )
                        for key in background_job_result.model_fields.keys():
                            if key in job.model_fields:
                                setattr(job, key, getattr(background_job_result, key))
                        session.add(job)
                        session.commit()
                        session.refresh(job)
                    except Exception as error:
                        # something went wrong, set it to error status

                        with Session(self.engine) as session:
                            job = session.exec(
                                select(Jobs).where(Jobs.id == job.id)
                            ).one()
                            job.status = JobStatus.Error.value
                            if "Connection error" in str(error):
                                logger.error(
                                    "Failed to connect to backend!",
                                    **job.model_dump(),
                                )
                                job.response = (
                                    "Failed to connect to backend, try again please!"
                                )

                            else:
                                job.response = str(error)
                                logger.error(
                                    "error processing job",
                                    error=job.response,
                                    **job.model_dump(),
                                )

                            job.updated = datetime.utcnow()
                            session.add(job)
                            session.commit()
                            session.refresh(job)

                except NoResultFound:
                    logger.debug(LogMessages.NoJobs)
                    time.sleep(1)
        logger.info(LogMessages.BackgroundPollerShutdown)
