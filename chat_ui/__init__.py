""" chat emulator using fastapi """

from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
import os.path
import random
import string
from pathlib import Path
import sys

from openai import AsyncOpenAI

from openai.types.chat import (
    ChatCompletionUserMessageParam,
)
from typing import Any, AsyncGenerator, Generator, List
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger
from sqlmodel import Session, select
import sqlmodel
from sqlalchemy.exc import NoResultFound

from starlette.middleware.sessions import SessionMiddleware

# from chat_ui.backgroundpoller import BackgroundPoller
from chat_ui.config import Config
from chat_ui.db import Jobs, Users

from chat_ui.models import (
    Job,
    JobDetail,
    NewJob,
    UserDetail,
    UserForm,
    WebSocketMessage,
    WebSocketResponse,
    validate_uuid,
)

logger.info("Config: {}", Config().model_dump())
connect_args = {"check_same_thread": False}
sqlite_url = f"sqlite:///{Config().db_path}"
engine = sqlmodel.create_engine(sqlite_url, echo=False, connect_args=connect_args)


def get_backend_client() -> AsyncOpenAI:
    """returns the backend client"""
    return AsyncOpenAI(
        api_key=Config().backend_api_key,
        base_url=Config().backend_url,
    )


async def handle_job(job: Jobs) -> None:
    """does the background job handling bit"""

    try:
        job.status = "running"
        logger.info("Starting job: {}", job)
        with Session(engine) as session:
            session.add(job)
            session.commit()
            session.refresh(job)
            # ok, let's do the prompty thing
            history = (
                # ChatCompletionSystemMessageParam(
                #     role="system", content=self.config.backend_system_prompt
                # ),
                ChatCompletionUserMessageParam(role="user", content=job.prompt),
            )
            logger.debug("Starting job: {}", job)
            start_time = datetime.utcnow().timestamp()
            completion = await get_backend_client().chat.completions.create(
                model="gpt-3.5-turbo",  # this field is currently unused
                messages=history,
                temperature=0.7,
                stream=False,
            )
            # example response
            # ChatCompletion(id='chatcmpl-y0a32z8y1k87uudh04maxl', choices=[Choice(finish_reason='stop', index=0, logprobs=None, message=ChatCompletionMessage(content="Cheese! It's a versatile food product that can be made from the pressed curds of milk. It's used in a variety of dishes, as a standalone snack, or even in non-edible applications like crafting and home improvement. There are many types of cheese around the world, each with its unique taste, texture, and production process. Do you have a favorite type of cheese, or would you like to know more about how it's made?", role='assistant', function_call=None, tool_calls=None))], created=1707962902, model='/Users/yaleman/.cache/lm-studio/models/TheBloke/Mixtral-8x7B-Instruct-v0.1-GGUF/mixtral-8x7b-instruct-v0.1.Q4_0.gguf', object='chat.completion', system_fingerprint=None, usage=CompletionUsage(completion_tokens=100, prompt_tokens=37, total_tokens=137))
            # TODO: build metadata
            logger.info(completion)
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
            session.add(job)
            session.commit()
            session.refresh(job)
            logger.success("Completed job: {}", job.model_dump_json())
    except Exception as error:
        logger.error("id={} error={}", job.id, error)
        with Session(engine) as session:
            job.status = "error"
            job.response = str(error)
            session.add(job)
            session.commit()
            session.refresh(job)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, Any]:
    """runs the background poller as the app is running"""
    # t = BackgroundPoller()
    # t.start()

    if "pytest" not in sys.modules:
        logger.info(
            "Checking for outstanding jobs on startup and setting them to error status"
        )

        with Session(engine) as session:
            sqlmodel.SQLModel.metadata.create_all(engine)
            jobs = session.exec(select(Jobs).where(Jobs.status == "running")).all()
            for job in jobs:
                logger.warning("Job id={} was running, setting to error", job.id)

                job.status = "error"
                job.response = "Server restarted, please try this again"
                session.add(job)
            session.commit()

    yield
    # t.shared_message = "stop"


# state = AppState()
app = FastAPI(lifespan=lifespan)
# app = FastAPI(lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=random.sample(string.ascii_letters + string.digits, 32),
    session_cookie="chatsession",
)


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        if "pytest" not in sys.modules:
            sqlmodel.SQLModel.metadata.create_all(engine)
        yield session


async def staticfile(filename: str, path: str) -> FileResponse:
    """returns a file from the path dir"""
    filepath = Path(os.path.join(os.path.dirname(__file__), path, filename))
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    return FileResponse(filepath)


@app.get("/img/{filename}")
async def img(filename: str) -> FileResponse:
    """returns the contents of html/index.html as a HTMLResponse object"""
    return await staticfile(filename, "img/")


@app.get("/css/{filename}")
async def css(filename: str) -> FileResponse:
    """returns a file from the css dir"""
    return await staticfile(filename, "css/")


@app.get("/js/{filename}")
async def js(filename: str) -> FileResponse:
    """returns a file from the js dir"""
    return await staticfile(filename, "js/")


@app.post("/user")
async def post_user(
    form: UserForm,
    session: Session = Depends(get_session),
) -> UserDetail:
    """post user"""
    newuser = Users(**form.model_dump())

    try:
        existing_user = session.exec(
            select(Users).where(Users.userid == newuser.userid)
        ).one()
        existing_user.name = newuser.name
        existing_user.updated = datetime.utcnow()
        session.add(existing_user)
        session.commit()
        session.refresh(existing_user)
        newuser = existing_user
    except NoResultFound:
        session.add(newuser)
        session.commit()
        session.refresh(newuser)
    return UserDetail(
        userid=str(newuser.userid),
        name=newuser.name,
        created=newuser.created,
        updated=newuser.updated,
    )


@app.post("/job")
async def create_job(
    job: NewJob,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
) -> Job:
    logger.info("Got new job: {}", job)

    newjob = Jobs(
        status="created",
        userid=job.userid,
        prompt=job.prompt,
        request_type=job.request_type,
    )
    session.add(newjob)
    session.commit()
    session.refresh(newjob)
    background_tasks.add_task(handle_job, newjob)
    return Job.from_jobs(newjob)


@app.get("/jobs")
async def jobs(
    userid: str,
    session: Session = Depends(get_session),
) -> List[Job]:
    """query the jobs for a given userid"""
    query = select(Jobs).where(Jobs.userid == userid)
    res = session.exec(query).all()
    return [Job.from_jobs(job) for job in res]


@app.get("/jobs/{userid}/{job_id}")
async def job_detail(
    userid: str,
    job_id: str,
    session: Session = Depends(get_session),
) -> JobDetail:
    try:
        query = select(Jobs).where(Jobs.userid == userid, Jobs.id == job_id)
        job = session.exec(query).first()
        return JobDetail.from_jobs(job)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Item not found")


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session: Session = Depends(get_session),
) -> None:
    await websocket.accept()
    if websocket.client is None:
        raise HTTPException(status_code=500, detail="Failed to accept websocket")
    logger.debug("websocket accepted from ip={}", websocket.client.host)
    try:
        while True:
            response = WebSocketResponse(message="error", payload="unknown message")
            try:
                data = WebSocketMessage.model_validate_json(
                    await websocket.receive_text()
                )
                if data.message == "jobs":
                    # serialize the jobs out so the websocket reader can parse them
                    try:
                        jobs = session.exec(
                            select(Jobs).where(
                                Jobs.userid == data.userid, Jobs.status != "hidden"
                            )
                        ).all()
                        payload = [Job.from_jobs(job) for job in jobs]
                        # logger.debug(jobs)
                        response = WebSocketResponse(message="jobs", payload=payload)
                    except Exception as error:
                        logger.error(
                            "websocket error={} ip={}", error, websocket.client.host
                        )
                        continue

                elif data.message == "delete":
                    if data.payload is not None:
                        id = validate_uuid(data.payload)
                        try:
                            query = select(Jobs).where(Jobs.id == id)
                            res = session.exec(query).one()
                            res.status = "hidden"
                            session.add(res)
                            session.commit()
                            session.refresh(res)
                            response = WebSocketResponse(
                                message="delete", payload=res.model_dump_json()
                            )
                        except NoResultFound:
                            logger.debug("No jobs found for userid={}", data.userid)
                            response = WebSocketResponse(
                                message="error",
                                payload=f"No job ID found matching {id}",
                            )
                    else:
                        response = WebSocketResponse(
                            message="error",
                            payload="no ID specified when asking for delete!",
                        )
            except Exception as error:
                logger.error("websocket error={} ip={}", error, websocket.client.host)
                response = WebSocketResponse(message="error", payload=str(error))
            # logger.debug(
            #     "websocket ip={} msg={}",
            #     websocket.client.host,
            #     response.as_message(),
            # )
            await websocket.send_text(response.as_message())
    except WebSocketDisconnect as disconn:
        logger.debug(
            "websocket disconnected ip={} msg={}", websocket.client.host, disconn
        )
    except Exception as error:
        logger.error("websocket error={} ip={}", error, websocket.client.host)


@app.get("/healthcheck")
async def healthcheck() -> str:
    """healthcheck endpoint"""
    return "OK"


@app.get("/")
async def index() -> HTMLResponse:
    """returns the contents of html/index.html as a HTMLResponse object"""
    htmlfile = os.path.join(os.path.dirname(__file__), "html/index.html")
    return HTMLResponse(open(htmlfile).read())
