""" chat emulator using fastapi """

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from functools import lru_cache
import json
import os
import os.path
import random
import string
from pathlib import Path
import sys

from typing import Any, AsyncGenerator, Generator, List, Tuple
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    BackgroundTasks,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger
from sqlmodel import Session, or_, select
import sqlmodel
from sqlalchemy.exc import NoResultFound

from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from chat_ui.backgroundpoller import BackgroundPoller

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
from chat_ui.utils import get_client_ip

connect_args = {"check_same_thread": False}
sqlite_url = f"sqlite:///{Config().db_path}"
engine = sqlmodel.create_engine(sqlite_url, echo=False, connect_args=connect_args)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, Any]:
    """runs the background poller as the app is running"""

    if "pytest" not in sys.modules:

        t = BackgroundPoller(engine)
        t.start()

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
                job.updated = datetime.utcnow()
                session.add(job)
            session.commit()
    yield
    t.message = "stop"


# state = AppState()
app = FastAPI(lifespan=lifespan)
# app = FastAPI(lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=random.sample(string.ascii_letters + string.digits, 32),
    session_cookie="chatsession",
)
app.add_middleware(GZipMiddleware)


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
    request: Request,
    session: Session = Depends(get_session),
) -> Job:
    logger.info("Got new job: {}", job)

    client_ip = get_client_ip(request)

    newjob = Jobs(
        status="created",
        userid=job.userid,
        prompt=job.prompt,
        request_type=job.request_type,
        client_ip=client_ip,
    )
    session.add(newjob)
    session.commit()
    session.refresh(newjob)
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


async def websocket_jobs(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    # serialize the jobs out so the websocket reader can parse them
    try:
        jobs = session.exec(
            select(Jobs).where(Jobs.userid == data.userid, Jobs.status != "hidden")
        ).all()
        payload = [Job.from_jobs(job) for job in jobs]
        # logger.debug(jobs)
        response = WebSocketResponse(message="jobs", payload=payload)
    except Exception as error:
        logger.error("websocket error={} ip={}", error, get_client_ip(websocket))
        response = WebSocketResponse(message="error", payload="Failed to get job list!")
    return response


async def websocket_resubmit(
    data: WebSocketMessage,
    session: Session,
    websocket: WebSocket,
) -> WebSocketResponse:
    try:
        query = select(Jobs).where(Jobs.id == data.payload, Jobs.userid == data.userid)
        res = session.exec(query).one()
        res.status = "created"
        res.response = ""
        res.updated = datetime.utcnow()
        session.add(res)
        session.commit()
        session.refresh(res)
        response = WebSocketResponse(message="resubmit", payload=res.model_dump_json())
    except NoResultFound:
        logger.debug("No jobs found for userid={} id={}", data.userid, data.payload)
        response = WebSocketResponse(
            message="error",
            payload=f"No job ID found matching {id}",
        )
    except Exception as error:
        logger.error(
            "Failed to handle resubmit request id={} error={}",
            id,
            error,
        )
        response = WebSocketResponse(
            message="error",
            payload=f"Error handling {id}",
        )
    return response


@lru_cache(maxsize=2)
def get_waiting_jobs(session: Session) -> Tuple[datetime, int]:
    try:
        res = (
            session.query(Jobs)
            .where(or_(Jobs.status == "created", Jobs.status == "running"))
            .count()
        )
        logger.debug("Waiting jobs: {}", res)
        return (datetime.utcnow(), res)
    except Exception as error:
        logger.debug("Failed to get waiting count: {}", error)
        return (datetime.utcnow(), 0)


async def websocket_waiting(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    """work out how many jobs are waiting"""

    try:
        # don't want to hit the DB too often...
        (last_update, waiting) = get_waiting_jobs(session)

        if last_update < datetime.utcnow() - timedelta(seconds=5):
            get_waiting_jobs.cache_clear()
            (last_update, waiting) = get_waiting_jobs(session)

        response = WebSocketResponse(
            message="waiting", payload=json.dumps(waiting, default=str)
        )

    except Exception as error:
        logger.error("websocket error={} ip={}", error, get_client_ip(websocket))
        response = WebSocketResponse(
            message="error", payload="Failed to get count of pending jobs..."
        )
    return response


async def websocket_delete(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    if data.payload is not None:
        id = validate_uuid(data.payload)
        try:
            query = select(Jobs).where(Jobs.id == id, Jobs.userid == data.userid)
            res = session.exec(query).one()
            res.status = "hidden"
            res.updated = datetime.utcnow()
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
    return response


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    background_tasks: BackgroundTasks,
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
                    response = await websocket_jobs(data, session, websocket)
                elif data.message == "delete":
                    response = await websocket_delete(data, session, websocket)
                elif data.message == "resubmit":
                    response = await websocket_resubmit(data, session, websocket)
                elif data.message == "waiting":
                    response = await websocket_waiting(data, session, websocket)
            except Exception as error:
                logger.error(
                    "websocket error={} src_ip={}", error, websocket.client.host
                )
                response = WebSocketResponse(message="error", payload=str(error))
            # logger.debug(
            #     "websocket ip={} msg={}",
            #     websocket.client.host,
            #     response.as_message(),
            # )
            await websocket.send_text(response.as_message())
    except WebSocketDisconnect as disconn:
        logger.debug(
            "websocket disconnected src_ip={} msg={}", websocket.client.host, disconn
        )
    except RuntimeError as error:
        if (
            "Unexpected ASGI message 'websocket.send', after sending 'websocket.close'"
            in str(error)
        ):
            logger.debug(
                "websocket message after send error={} ip={}",
                error,
                websocket.client.host,
            )
        else:
            logger.error("websocket error={} src_ip={}", error, websocket.client.host)
    except Exception as error:
        logger.error("websocket error={} src_ip={}", error, websocket.client.host)


@app.get("/healthcheck")
async def healthcheck() -> str:
    """healthcheck endpoint"""
    return "OK"


@app.get("/")
async def index() -> HTMLResponse:
    """returns the contents of html/index.html as a HTMLResponse object"""
    htmlfile = os.path.join(os.path.dirname(__file__), "html/index.html")
    return HTMLResponse(open(htmlfile).read())
