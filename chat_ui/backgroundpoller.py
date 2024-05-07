""" This polls the backend to check if it is up and running """

import asyncio
from datetime import datetime, UTC
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
from chat_ui.db import JobAnalysis, Jobs
from chat_ui.models import JobStatus, LogMessages, AnalysisType
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
    created: datetime = Field(datetime.now(UTC))
    updated: Optional[datetime] = None
    prompt: str
    response: Optional[str] = None
    request_type: str
    runtime: Optional[float] = None
    job_metadata: Optional[str] = None
    history: List[Jobs] = []
    sessionid: UUID

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
            sessionid=job.sessionid,
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
    def __init__(self, engine: Engine, model_name: str):
        super().__init__()
        self.config = Config()
        self.model_name = model_name
        self.message = "run"
        self.engine = engine
        self.event_loop = asyncio.new_event_loop()

    @classmethod
    def check_history_tokens(
        cls,
        job: BackgroundJob,
    ) -> Tuple[BackgroundJob, list[tuple[str, int]], int]:
        """checks the history tokens and removes the oldest until we're under the token limit"""
        history_tokens = rough_history_tokens(job.history)
        total_history_tokens = sum([t[1] for t in history_tokens])
        while total_history_tokens > 2048:
            job.history.pop(0)
            history_tokens = rough_history_tokens(job.history)
            total_history_tokens = sum([t[1] for t in history_tokens])
        return (job, history_tokens, total_history_tokens)

    async def handle_job(self, job: BackgroundJob) -> Jobs:
        """handles a prompt job"""
        start_time = datetime.now(UTC).timestamp()
        client = get_backend_client()
        # we need to make sure we're under the token limit
        job, history_tokens, total_history_tokens = self.check_history_tokens(job)
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
            model=self.model_name,
            messages=history,
            temperature=0.7,
            stream=False,
        )

        logger.debug(
            LogMessages.JobCompletionOutput,
            userid=job.userid,
            job_id=job.id,
            **completion.model_dump(),
        )
        if completion.usage is not None:
            usage = completion.usage.model_dump()
        else:
            usage = {}

        job.runtime = datetime.now(UTC).timestamp() - start_time
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

    def add_related_jobs(self, session: Session, backgroundjob: BackgroundJob) -> None:
        """get related jobs"""
        try:
            query = select(Jobs).where(
                Jobs.userid == backgroundjob.userid,
                Jobs.status == JobStatus.Complete.value,
            )
            # TODO: sort the history by "created" field
            backgroundjob.history = [job for job in session.exec(query).all()]
        except Exception as error:
            logger.error(
                "failed to pull history",
                error=error,
                userid=backgroundjob.userid,
                id=backgroundjob.id,
            )

    def process_prompt(self, job: Jobs, session: Session) -> None:
        """handle the prompt processing"""
        # update the job to say we're doing the thing
        job.mark_running(session)

        backgroundjob = BackgroundJob.from_jobs(job)
        self.add_related_jobs(session, backgroundjob)

        try:
            start_log_entry = {**backgroundjob.model_dump()}
            history = start_log_entry.pop(
                "history"
            )  # need to strip this off because it's just huge
            logger.debug("job history", id=job.id, userid=job.userid, history=history)

            logger.info(LogMessages.JobStarted, **start_log_entry)
            # here's where we pass it to the backend
            background_job_result = self.event_loop.run_until_complete(
                self.handle_job(backgroundjob)
            )
            job.updated = datetime.now(UTC)
            background_job_result.model_dump(exclude_unset=False, exclude_none=False)
            for key in background_job_result.model_fields.keys():
                if key in job.model_fields:
                    setattr(job, key, getattr(background_job_result, key))
            logger.debug("Saving job: {}", job.model_dump())
            session.add(job)
            session.commit()
            session.refresh(job)
        # something went wrong, set it to error status
        except Exception as error:
            # clear out the existing cache of objects
            session.expire_all()
            job = session.exec(select(Jobs).where(Jobs.id == job.id)).one()
            job.status = JobStatus.Error.value
            if "Connection error" in str(error):
                logger.error(
                    "Failed to connect to backend!",
                    **job.model_dump(),
                )
                job.response = "Failed to connect to backend, try again please!"

            else:
                job.response = str(error)
                logger.error(
                    "error processing job",
                    error=job.response,
                    **job.model_dump(),
                )

            job.updated = datetime.now(UTC)
            session.add(job)
            session.commit()

    def process_outstanding_prompts(self, session: Session) -> None:
        """process any outstanding prompt requests"""
        try:
            # get any new prompt requests
            job = session.exec(
                select(Jobs).where(Jobs.status == JobStatus.Created.value)
            ).one()
            self.process_prompt(job, session)

        except NoResultFound:
            # logger.debug(LogMessages.NoJobs)
            # don't just infinispin
            time.sleep(0.1)

    async def process_outstanding_analyses(self, session: Session) -> Optional[UUID]:
        """if there's an outstanding analysis request, let's handle that

        returns the UUID processed, or None if nothing was processed"""
        query = select(JobAnalysis).where(JobAnalysis.status == JobStatus.Created.value)

        try:
            analysis_job = session.exec(query).one()
        except NoResultFound:
            return None

        job_query = select(Jobs).where(Jobs.id == analysis_job.jobid)
        if analysis_job.analysis_type != AnalysisType.Prompt:
            # if we're only analysing the prompt, we're good, but if we need the response should skip error jobs
            job_query = job_query.where(Jobs.status != JobStatus.Error.value)

        # check if there's a job at all, and only mark it as an error if it's non-existent
        try:
            job = session.exec(job_query).one()
        except NoResultFound:
            logger.error(
                "No job matching the UUID for an analysis job",
                id=analysis_job.analysisid,
                jobid=analysis_job.jobid,
            )
            analysis_job.mark_error(session, "No completed job matching the jobid")
            return None
        if job is None:
            logger.error(
                "No completed job matching the UUID for an analysis job",
                id=analysis_job.analysisid,
                jobid=analysis_job.jobid,
            )
            analysis_job.mark_error(session, "No completed job matching the jobid")
            return None
        if (
            Jobs.status != JobStatus.Complete.value
            and analysis_job.analysis_type == AnalysisType.Response
        ):
            logger.error(
                "job is not completed, can't handle response",
                jobid=job.id,
                analysisid=analysis_job.analysisid,
            )
            return None

        if analysis_job.analysis_type in (AnalysisType.Response):
            if job.response is None or job.response.strip() == "":
                logger.error(
                    "No response when prompting to analyse, nothing to do!",
                    job_id=job.id,
                )
                # TODO: check if there's a job at all, and only mark it as an error if it's non-existent
                analysis_job.mark_error(
                    session, "No response when prompting to analyse, nothing to do!"
                )
                return None

        # now we hand it to the LLM to process
        start_time = datetime.now(UTC).timestamp()

        client = get_backend_client()

        # build the prompt for the thingie
        message = f"{analysis_job.preprompt}\n"
        if analysis_job.analysis_type in [
            AnalysisType.Prompt,
            AnalysisType.PromptAndResponse,
        ]:
            message += f"the prompt was:\n\n{job.prompt}\n\n"
        elif analysis_job.analysis_type in [
            AnalysisType.Response,
            AnalysisType.PromptAndResponse,
        ]:
            message += f"the response was:\n{job.response}\n"

        # we need to make sure we're under the token limit
        # TODO: check we're not running over tokens
        history = [
            ChatCompletionUserMessageParam(content=message, role="user"),
        ]

        logger.info(
            LogMessages.AnalysisJobStarting,
            start_time=start_time,
            full_prompt=message,
            **analysis_job.model_dump(mode="json"),
        )

        completion = await client.chat.completions.create(
            model=self.model_name,
            messages=history,
            temperature=0.7,
            stream=False,
        )

        if completion.usage is not None:
            usage = completion.usage.model_dump()
        else:
            usage = {}

        response = completion.choices[0].message.content
        analysis_job.response = response
        job.job_metadata = json.dumps(
            {
                "runtime": datetime.now(UTC).timestamp() - start_time,
                "model": completion.model,
                "usage": usage,
            },
            default=str,
        )
        logger.info(
            LogMessages.AnalysisJobCompletionOutput,
            start_time=start_time,
            **analysis_job.model_dump(mode="json"),
        )

        # # so it's slightly easier to parse in the logs
        logger.info(
            LogMessages.AnalysisJobMetadata,
            job_id=analysis_job.analysisid,
            userid=analysis_job.userid,
            **usage,
        )

        analysis_job.status = JobStatus.Complete
        analysis_job.updated = datetime.now(UTC)
        session.add(analysis_job)
        session.commit()
        session.refresh(analysis_job)
        return analysis_job.analysisid

    def run(self) -> None:
        """polls for jobs to run"""
        while self.message == "run":
            with Session(self.engine) as session:
                # do the prompts
                self.process_outstanding_prompts(session)
                # do the prompt analysis
                self.event_loop.run_until_complete(
                    self.process_outstanding_analyses(session)
                )
        logger.info(LogMessages.BackgroundPollerShutdown)
