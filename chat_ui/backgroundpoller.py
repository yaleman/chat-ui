""" This polls the backend to check if it is up and running """

import asyncio
from datetime import datetime
import json
import threading
import time
from typing import List, Optional, Union
from uuid import UUID, uuid4

from loguru import logger
from pydantic import BaseModel, Field

from sqlmodel import Session, select

from sqlalchemy import Engine
from sqlalchemy.exc import NoResultFound
from chat_ui.config import Config
from chat_ui.db import Jobs
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
            logger.debug("adding user prompt to history: {}", job.prompt)
            history.append(
                ChatCompletionUserMessageParam(content=job.prompt, role="user")
            )
            if job.response is not None and job.response.strip():
                logger.debug("adding response to history: {}", job.prompt)
                history.append(
                    ChatCompletionAssistantMessageParam(
                        content=job.response, role="assistant"
                    )
                )
        history.append(ChatCompletionUserMessageParam(content=self.prompt, role="user"))
        return history


class BackgroundPoller(threading.Thread):
    def __init__(self, engine: Engine):
        super().__init__()
        self.config = Config()
        self.message = "run"
        self.engine = engine
        self.event_loop = asyncio.new_event_loop()

    async def handle_job(self, job: BackgroundJob) -> Jobs:

        start_time = datetime.utcnow().timestamp()
        completion = await get_backend_client().chat.completions.create(
            model="gpt-3.5-turbo",  # this field is currently unused
            messages=job.get_history(),
            temperature=0.7,
            stream=False,
        )

        logger.debug(
            "completion output",
            userid=job.userid,
            job_id=job.id,
            **completion.model_dump(),
        )
        if completion.usage is not None:
            usage = completion.usage.model_dump()
        else:
            usage = None
        job.runtime = datetime.utcnow().timestamp() - start_time

        job.response = completion.choices[0].message.content
        job.job_metadata = json.dumps(
            {
                "model": completion.model,
                "usage": usage,
            },
            default=str,
        )
        job.status = "complete"
        res = Jobs.from_backgroundjob(job)
        logger.info("job completed", **res.model_dump())
        return res

    def run(self) -> None:
        while self.message == "run":
            with Session(self.engine) as session:
                try:
                    job = session.exec(
                        select(Jobs).where(Jobs.status == "created")
                    ).first()
                    if job is None:
                        time.sleep(0.1)
                        continue
                    job.status = "running"
                    job.updated = datetime.utcnow()
                    session.add(job)
                    session.commit()
                    session.refresh(job)

                    backgroundjob = BackgroundJob.from_jobs(job)
                    query = select(Jobs).where(
                        Jobs.userid == backgroundjob.userid,
                        Jobs.status == "complete",
                    )
                    try:
                        backgroundjob.history = [
                            job for job in session.exec(query).all()
                        ]
                    except Exception as error:
                        logger.error(
                            "failed to pull history",
                            error=error,
                            userid=job.userid,
                            job_id=job.id,
                        )
                    # TODO: sort the history by "created" field

                    try:
                        logger.info("starting job", **backgroundjob.model_dump())
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
                            job.status = "error"
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
                            job.updated = datetime.utcnow()
                            session.add(job)
                            session.commit()
                            session.refresh(job)

                except NoResultFound:
                    logger.debug("No waiting jobs found")
                    time.sleep(1)
        logger.info("Background poller is stopping")
