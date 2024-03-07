""" chat emulator using fastapi """

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import json
import os
import os.path
import random
import string
from pathlib import Path
import sys
import traceback


from typing import Any, AsyncGenerator, Generator, List
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
from prometheus_fastapi_instrumentator import Instrumentator


from sqlmodel import Session, select
import sqlmodel
from sqlalchemy.exc import NoResultFound

from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from chat_ui.backgroundpoller import BackgroundPoller

# from chat_ui.backgroundpoller import BackgroundPoller
from chat_ui.config import Config
from chat_ui.db import JobFeedback, Jobs, Users
from chat_ui.logs import sink

from chat_ui.models import (
    Job,
    JobDetail,
    JobStatus,
    LogMessages,
    NewJob,
    UserDetail,
    UserForm,
    WebSocketMessage,
    WebSocketMessageType,
    WebSocketResponse,
    validate_uuid,
)
from chat_ui.utils import get_client_ip, get_waiting_jobs, html_from_response

logger.remove()
logger.add(sink=sink)


connect_args = {"check_same_thread": False}
sqlite_url = f"sqlite:///{Config().db_path}"
engine = sqlmodel.create_engine(sqlite_url, echo=False, connect_args=connect_args)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, Any]:
    """runs the background poller as the app is running"""

    instrumentator.expose(app, should_gzip=True)

    if "pytest" not in sys.modules:

        t = BackgroundPoller(engine)
        t.start()

        logger.info(
            "Checking for outstanding jobs on startup and setting them to error status"
        )

        with Session(engine) as session:
            sqlmodel.SQLModel.metadata.create_all(engine)
            jobs = session.exec(
                select(Jobs).where(Jobs.status == JobStatus.Running.value)
            ).all()
            for job in jobs:
                logger.warning("Job was running, setting to error", job_id=job.id)

                job.status = JobStatus.Error.value
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
instrumentator = Instrumentator().instrument(app)


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
    request: Request,
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
    res = UserDetail(
        userid=str(newuser.userid),
        name=newuser.name,
        created=newuser.created,
        updated=newuser.updated,
    )
    logger.info(
        LogMessages.UserUpdate, src_ip=get_client_ip(request), **res.model_dump()
    )
    return res


@app.post("/job")
async def create_job(
    job: NewJob,
    request: Request,
    session: Session = Depends(get_session),
) -> Job:

    client_ip = get_client_ip(request)

    newjob = Jobs(
        status=JobStatus.Created.value,
        userid=job.userid,
        prompt=job.prompt,
        request_type=job.request_type,
        client_ip=client_ip,
    )

    logger.info(
        LogMessages.NewJob,
        src_ip=get_client_ip(request),
        **newjob.model_dump(round_trip=False, warnings=False),
    )
    session.add(newjob)
    session.commit()
    session.refresh(newjob)
    return Job.from_jobs(newjob, None)


@app.get("/jobs")
async def jobs(
    userid: str,
    session: Session = Depends(get_session),
) -> List[Job]:
    """query the jobs for a given userid"""
    query = select(Jobs).where(Jobs.userid == userid)
    return [Job.from_jobs(job, None) for job in session.exec(query).all()]


@app.get("/jobs/{userid}/{job_id}")
async def job_detail(
    userid: str,
    job_id: str,
    session: Session = Depends(get_session),
) -> JobDetail:
    try:
        query = select(Jobs).where(Jobs.userid == userid, Jobs.id == job_id)
        job = session.exec(query).first()
        # convert the output into HTML
        # technically this'll be caught as an exception, but it doesn't hurt to be explicit
        if job is not None:
            if job.response is not None:
                job.response = html_from_response(job.response)
        session.reset()
        feedback = JobFeedback.get_feedback(session, job_id)
        return JobDetail.from_jobs(job, feedback)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Item not found")


async def websocket_jobs(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    # serialize the jobs out so the websocket reader can parse them
    try:
        jobs = session.exec(
            select(Jobs).where(
                Jobs.userid == data.userid, Jobs.status != JobStatus.Hidden.value
            )
        ).all()
        payload = [Job.from_jobs(job, None) for job in jobs]
        response = WebSocketResponse(
            message=WebSocketMessageType.Jobs.value, payload=payload
        )
    except Exception as error:
        logger.error(
            "websocket_jobs error",
            error=error,
            src_ip=get_client_ip(websocket),
            **data.model_dump(),
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value, payload="Failed to get job list!"
        )
    return response


async def websocket_resubmit(
    data: WebSocketMessage,
    session: Session,
    websocket: WebSocket,
) -> WebSocketResponse:
    try:

        query = select(Jobs).where(Jobs.id == data.payload, Jobs.userid == data.userid)
        res = session.exec(query).one()
        # only accept the resubmit if it was an error
        if res.status == JobStatus.Error.value:
            res.status = JobStatus.Created.value
            res.response = ""
            res.updated = datetime.utcnow()
            session.add(res)
            session.commit()
            session.refresh(res)
            logger.debug(
                LogMessages.Resubmitted,
                src_ip=get_client_ip(websocket),
                **data.model_dump(),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Resubmit.value,
                payload=res.model_dump_json(),
            )
        else:
            logger.debug(
                LogMessages.RejectedResubmit,
                status=res.status,
                src_ip=get_client_ip(websocket),
                **data.model_dump(),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Error.value,
                payload=f"Job {data.payload} is not in an error state",
            )
    except NoResultFound:
        logger.debug(
            LogMessages.NoJobs, src_ip=get_client_ip(websocket), **data.model_dump()
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload=f"No job ID found matching {data.payload}",
        )
    except Exception as error:
        logger.error(
            LogMessages.FailedResubmit,
            error=error,
            src_ip=get_client_ip(websocket),
            **data.model_dump(),
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload=f"Error handling {data.payload}",
        )
    return response


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
            message=WebSocketMessageType.Waiting.value,
            payload=json.dumps(waiting, default=str),
        )

    except Exception as error:
        logger.error(
            LogMessages.WebsocketError,
            error=error,
            src_ip=get_client_ip(websocket),
            **data.model_dump(),
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="Failed to get count of pending jobs...",
        )
    return response


async def websocket_feedback(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    """handle a user's feedback response"""
    if data.payload is None:
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="No payload specified when sending feedback!",
        )
        return response
    try:
        feedback = JobFeedback(
            **json.loads(data.payload or ""), src_ip=get_client_ip(websocket)
        )
    except Exception as error:
        logger.error(
            LogMessages.WebsocketError,
            src_ip=get_client_ip(websocket),
            error=str(error),
            **data.model_dump(),
        )
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="Exception handling feedback, please try again!",
        )
        return response

    try:
        if JobFeedback.has_feedback(session, str(feedback.jobid)):
            try:
                query = select(JobFeedback).where(
                    JobFeedback.jobid == str(feedback.jobid)
                )
                existing_feedback = session.exec(query).one()
                for field in existing_feedback.model_fields:
                    if field in feedback.model_fields:
                        setattr(existing_feedback, field, getattr(feedback, field))
                existing_feedback.created = datetime.utcnow()
                session.add(existing_feedback)
                session.commit()
                session.refresh(existing_feedback)
                response = WebSocketResponse(
                    message=WebSocketMessageType.Feedback.value, payload="OK"
                )
                logger.debug(
                    LogMessages.JobFeedback,
                    **existing_feedback.model_dump(warnings=False, round_trip=True),
                )
            except NoResultFound:
                logger.error(
                    LogMessages.NoJobs.value,
                    src_ip=get_client_ip(websocket),
                    **feedback.model_dump(),
                )
                response = WebSocketResponse(
                    message=WebSocketMessageType.Error.value,
                    payload="No job!",
                )

        else:
            session.add(feedback)
            session.commit()
            session.refresh(feedback)
            logger.info(
                LogMessages.JobFeedback,
                **existing_feedback.model_dump(warnings=False, round_trip=True),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Feedback.value, payload="OK"
            )
    except Exception:
        logger.error(LogMessages.WebsocketError, error=traceback.format_exc())
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="Exception handling feedback, please try again!",
        )
    return response


async def websocket_delete(
    data: WebSocketMessage, session: Session, websocket: WebSocket
) -> WebSocketResponse:
    if data.payload is not None:
        job_id = validate_uuid(data.payload)
        try:
            query = select(Jobs).where(Jobs.id == job_id, Jobs.userid == data.userid)
            res = session.exec(query).one()
            res.status = JobStatus.Hidden.value
            res.updated = datetime.utcnow()
            session.add(res)
            session.commit()
            session.refresh(res)
            logger.info(
                LogMessages.JobDeleted,
                src_ip=get_client_ip(websocket),
                **data.model_dump(),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Delete, payload=res.model_dump_json()
            )
        except NoResultFound:
            logger.info(
                LogMessages.DeleteNotFound,
                job_id=job_id,
                src_ip=get_client_ip(websocket),
                **data.model_dump(),
            )
            response = WebSocketResponse(
                message=WebSocketMessageType.Error.value,
                payload=f"No job ID found matching {job_id}",
            )
    else:
        response = WebSocketResponse(
            message=WebSocketMessageType.Error.value,
            payload="No ID specified when asking for delete!",
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
    logger.debug("New websocket connection", src_ip=get_client_ip(websocket))
    try:
        while True:
            response = WebSocketResponse(
                message=WebSocketMessageType.Error.value, payload="unknown message"
            )
            try:
                raw_msg = await websocket.receive_text()
                data = WebSocketMessage.model_validate_json(raw_msg)
            except Exception as error:
                logger.error(
                    LogMessages.WebsocketError.value,
                    error=error,
                    src_ip=get_client_ip(websocket),
                    raw_msg=raw_msg,
                )
                response = WebSocketResponse(
                    message=WebSocketMessageType.Error.value, payload=str(error)
                )
            if data.message == WebSocketMessageType.Jobs.value:
                response = await websocket_jobs(data, session, websocket)
            elif data.message == WebSocketMessageType.Delete.value:
                response = await websocket_delete(data, session, websocket)
            elif data.message == WebSocketMessageType.Resubmit.value:
                response = await websocket_resubmit(data, session, websocket)
            elif data.message == WebSocketMessageType.Waiting.value:
                response = await websocket_waiting(data, session, websocket)
            elif data.message == WebSocketMessageType.Feedback.value:
                response = await websocket_feedback(data, session, websocket)

            await websocket.send_text(response.as_message())
    except WebSocketDisconnect as disconn:
        logger.debug(
            f"Websocket disconnected: {disconn}", src_ip=get_client_ip(websocket)
        )
    except RuntimeError as error:
        if (
            "Unexpected ASGI message 'websocket.send', after sending 'websocket.close'"
            in str(error)
        ):
            logger.debug(
                "Websocket_message after send",
                error=str(error),
                src_ip=get_client_ip(websocket),
            )
        else:
            logger.error(
                LogMessages.WebsocketError, src_ip=get_client_ip(websocket), error=error
            )
    # except Exception as error:
    #     logger.error(
    #         LogMessages.WebsocketError, src_ip=get_client_ip(websocket), error=error
    #     )


@app.get("/healthcheck")
async def healthcheck() -> str:
    """healthcheck endpoint"""
    return "OK"


@app.get("/")
async def index() -> HTMLResponse:
    """returns the contents of html/index.html as a HTMLResponse object"""
    htmlfile = os.path.join(os.path.dirname(__file__), "html/index.html")
    return HTMLResponse(open(htmlfile).read())
