""" chat emulator using fastapi """

from contextlib import asynccontextmanager
from datetime import datetime, UTC
import json
import os
import os.path
import random
import string
from pathlib import Path
import sys


from typing import Any, AsyncGenerator, Generator, List, Sequence
from uuid import UUID, uuid4
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.websockets import WebSocketState
from loguru import logger

from prometheus_fastapi_instrumentator import Instrumentator


from sqlmodel import Session, or_, select
import sqlmodel
from sqlalchemy.exc import NoResultFound
import sqlalchemy.engine
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from chat_ui.backgroundpoller import BackgroundPoller
from chat_ui.websocket_handlers import (
    websocket_delete,
    websocket_feedback,
    websocket_resubmit,
    websocket_waiting,
)

from .config import Config
from .db import ChatUiDBSession, JobFeedback, Jobs, Users
from .logs import sink

from .forms import SessionUpdateForm, NewJobForm, UserDetail, UserForm
from chat_ui.models import (
    Job,
    JobDetail,
    JobStatus,
    LogMessages,
    WebSocketMessage,
    WebSocketMessageType,
    WebSocketResponse,
)
from chat_ui.utils import get_client_ip, html_from_response

logger.remove()
logger.add(sink=sink)

if "pytest" in sys.modules:
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}
sqlite_url = f"sqlite:///{Config().db_path}"
engine = sqlmodel.create_engine(sqlite_url, echo=False, connect_args=connect_args)

# helpful with lifecycle handlers


def migrate_database(engine: sqlalchemy.engine.Engine) -> None:
    """migrate the database"""
    # backfill any chats that don't have sessions assigned after making sure the table exists
    with Session(engine) as session:
        try:
            session.exec(select(Jobs).where(Jobs.sessionid is None))
        except Exception as oe:
            if "no such column: jobs.sessionid" in str(oe):
                print("Adding sessionid column to jobs table!")
                session.autoflush = False

                session.exec(  # type: ignore
                    sqlmodel.text("ALTER TABLE jobs ADD COLUMN sessionid VARCHAR(32)")
                )
                session.commit()
            else:
                logger.error(oe)
                sys.exit(1)
    with Session(engine) as session:
        # identify the users that need upaating
        logger.info("Checking for jobs with no session ID assigned.")
        users = session.exec(  # type: ignore
            sqlmodel.text("select distinct userid from jobs where sessionid is NULL")
        ).all()

        # generate a chat session for each user
        for user in users:
            sessionid = uuid4()
            logger.info("fixing jobs for user", userid=user[0], sessionid=sessionid)
            session.add(ChatUiDBSession(userid=user[0], sessionid=str(sessionid)))
            session.commit()
            numjobs = session.scalar(
                sqlmodel.text(
                    "select count(id) from jobs where sessionid is NULL and userid=:userid"
                ).bindparams(userid=user[0])
            )
            session.exec(  # type: ignore
                sqlmodel.text(
                    "UPDATE jobs set sessionid=:sessionid where sessionid is NULL and userid=:userid"
                ).bindparams(sessionid=str(sessionid), userid=user[0])
            )
            logger.info(
                "set sessionids", userid=user[0], count=numjobs, sessionid=sessionid
            )
        session.commit()


def startup_check_outstanding_jobs() -> None:
    logger.info(
        "Checking for outstanding jobs on startup and setting them to error status"
    )
    with Session(engine) as session:
        jobs = session.exec(
            select(Jobs).where(Jobs.status == JobStatus.Running.value)
        ).all()
        for job in jobs:
            logger.warning("Job was running, setting to error", job_id=job.id)
            job.status = JobStatus.Error.value
            job.response = "Server restarted, please try this again"
            job.updated = datetime.now(UTC)
            session.add(job)
        session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, Any]:
    """runs the background poller as the app is running"""

    instrumentator.expose(app)

    if "pytest" not in sys.modules:

        # create all the tables
        sqlmodel.SQLModel.metadata.create_all(engine)
        migrate_database(engine)
        startup_check_outstanding_jobs()

        t = BackgroundPoller(engine)
        t.start()
    logger.info("Prechecks done, starting app")

    yield

    logger.info("Shutting down app")

    t.message = "stop"


app = FastAPI(lifespan=lifespan)
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
        existing_user.updated = datetime.now(UTC)
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
    job: NewJobForm,
    request: Request,
    session: Session = Depends(get_session),
) -> Job:
    """create a new job"""
    client_ip = get_client_ip(request)

    newjob = Jobs.from_newjobform(job, client_ip=client_ip)

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
    userid: UUID,
    sessionid: str | None = None,
    since: float | None = None,
    session: Session = Depends(get_session),
) -> List[Job]:
    """query the jobs for a given userid

    extra filters:

    - sessionid (a given chat session id)
    - since (a unix timestamp, only return jobs created/updated since this time)
    """
    query = select(Jobs).where(Jobs.userid == userid)
    if sessionid is not None:
        query = query.where(Jobs.sessionid == sessionid)
    if since is not None:
        query = query.where(
            or_(
                (
                    Jobs.updated is not None
                    and Jobs.updated >= datetime.fromtimestamp(since, UTC)
                ),
                Jobs.created >= datetime.fromtimestamp(since, UTC),
            )
        )
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
        payload = json.loads(data.payload or "")
        jobs = session.exec(
            select(Jobs).where(
                Jobs.userid == data.userid,
                Jobs.status != JobStatus.Hidden.value,
                or_(
                    Jobs.created
                    > datetime.fromtimestamp(float(payload.get("since", 0)), UTC),
                    (
                        Jobs.updated is not None
                        and Jobs.updated
                        > datetime.fromtimestamp(float(payload.get("since", 0)), UTC)
                    ),
                ),
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


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    session: Session = Depends(get_session),
) -> None:
    # await websocketmanager.connect(websocket)
    await websocket.accept()

    if websocket.client is None:
        raise HTTPException(status_code=500, detail="Failed to accept websocket")
    logger.debug("New websocket connection", src_ip=get_client_ip(websocket))
    try:
        while websocket.client_state == WebSocketState.CONNECTED:
            try:
                raw_msg = ""
                raw_msg = await websocket.receive_text()
                response = WebSocketResponse(
                    message=WebSocketMessageType.Error.value, payload="unknown message"
                )
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
                await websocket.send_text(response.as_message())
                await websocket.close()
                return

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
        return
    except Exception as error:
        logger.error(error)
        return


@app.get("/healthcheck")
async def healthcheck() -> str:
    """healthcheck endpoint"""
    return "OK"


def create_session(userid: UUID, session: Session) -> ChatUiDBSession:
    """create a new session"""
    new_session = ChatUiDBSession(userid=userid)
    session.add(new_session)
    session.commit()
    session.refresh(new_session)
    return new_session


@app.post("/session/new/{userid}")
async def session_new(
    userid: UUID, session: Session = Depends(get_session)
) -> ChatUiDBSession:
    # check the userid exists
    try:
        if session.exec(select(Users).where(Users.userid == str(userid))).one() is None:
            raise HTTPException(status_code=404, detail="User not found")
    except NoResultFound:
        raise HTTPException(status_code=404, detail="User not found")

    # create the new entry in the db
    new_session = create_session(userid, session)

    logger.info(LogMessages.NewSession, **new_session.model_dump(mode="json"))
    return new_session


@app.post("/session/{userid}/{sessionid}")
async def session_update(
    userid: UUID,
    sessionid: UUID,
    form: SessionUpdateForm,
    session: Session = Depends(get_session),
) -> ChatUiDBSession:

    try:
        chatsession = session.exec(
            select(ChatUiDBSession).where(
                ChatUiDBSession.userid == str(userid),
                ChatUiDBSession.sessionid == str(sessionid),
            )
        ).one()

    except NoResultFound:
        raise HTTPException(status_code=404, detail="Session not found")
    if chatsession is None:
        raise HTTPException(status_code=404, detail="Session not found")
    chatsession.name = form.name
    session.add(chatsession)
    session.commit()
    session.refresh(chatsession)
    return chatsession


@app.get("/sessions/{userid}")
async def get_user_sessions(
    userid: UUID, create: bool = True, session: Session = Depends(get_session)
) -> Sequence[ChatUiDBSession]:
    try:
        if session.exec(select(Users).where(Users.userid == str(userid))).one() is None:
            raise HTTPException(status_code=404, detail="User not found")

    except NoResultFound:
        raise HTTPException(status_code=404, detail="User not found")

    query = (
        select(ChatUiDBSession)
        .where(ChatUiDBSession.userid == str(userid))
        .order_by(ChatUiDBSession.created.desc())  # type: ignore
        # because desc isn't a method of datetime but it works in sqlalchemy
    )
    res: Sequence[ChatUiDBSession] = session.exec(query).all()

    # if there aren't any sessions, create one
    if len(res) == 0 and create:
        res = [create_session(userid, session)]

    return res


@app.get("/")
async def index() -> HTMLResponse:
    """returns the contents of html/index.html as a HTMLResponse object"""
    return HTMLResponse(
        Path(os.path.join(os.path.dirname(__file__), "html/index.html")).read_bytes()
    )
