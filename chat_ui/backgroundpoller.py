""" This polls the backend to check if it is up and running """

import asyncio
from datetime import datetime
import json
import threading
import time

from loguru import logger

from sqlmodel import Session, select

from sqlalchemy.exc import NoResultFound
from sqlalchemy.engine import Engine
from chat_ui.config import Config
from chat_ui.db import Jobs
from chat_ui.utils import get_backend_client


from openai.types.chat import (
    ChatCompletionUserMessageParam,
)


class BackgroundPoller(threading.Thread):
    def __init__(self, engine: Engine):
        super().__init__()
        self.config = Config()
        self.message = "run"
        self.engine = engine
        self.event_loop = asyncio.new_event_loop()

    async def handle_job(self, job: Jobs) -> Jobs:
        history = (
            # ChatCompletionSystemMessageParam(
            #     role="system", content=self.config.backend_system_prompt
            # ),
            ChatCompletionUserMessageParam(role="user", content=job.prompt),
        )
        start_time = datetime.utcnow().timestamp()
        completion = await get_backend_client().chat.completions.create(
            model="gpt-3.5-turbo",  # this field is currently unused
            messages=history,
            temperature=0.7,
            stream=False,
        )
        logger.debug("completion result", **completion.model_dump())
        response = completion.choices[0].message.content
        if completion.usage is not None:
            usage = completion.usage.model_dump()
        else:
            usage = None
        job.runtime = datetime.utcnow().timestamp() - start_time

        job.response = response
        job.job_metadata = json.dumps(
            {
                "model": completion.model,
                "usage": usage,
            },
            default=str,
        )
        job.status = "complete"
        return job

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
                    try:
                        logger.debug("starting job", **job.model_dump())
                        job = self.event_loop.run_until_complete(self.handle_job(job))
                        job.updated = datetime.utcnow()
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
