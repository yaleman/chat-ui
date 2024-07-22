""" chat emulator using fastapi """

from contextlib import asynccontextmanager
from datetime import datetime, UTC
import os
import os.path
import random
import string
from pathlib import Path
import sys


from typing import Annotated, Any, AsyncGenerator, Generator, List, Optional, Sequence
from uuid import UUID
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Header,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.websockets import WebSocketState
from loguru import logger

from sqlmodel import Session, or_, select
import sqlmodel

from sqlalchemy import func
from sqlalchemy.exc import NoResultFound
import sqlalchemy.engine
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from opentelemetry import trace

from chat_ui.backgroundpoller import BackgroundPoller
from chat_ui.enums import Urls
from chat_ui.websocket_handlers import (
    websocket_delete,
    websocket_feedback,
    websocket_jobs,
    websocket_resubmit,
    websocket_waiting,
)

from .config import Config
from .db import ChatUiDBSession, JobAnalysis, JobFeedback, Jobs, Users, migrate_database
from .logs import sink

from .forms import SessionUpdateForm, NewJobForm, UserDetail, UserForm
from chat_ui.models import (
    AnalyzeForm,
    Job,
    JobDetail,
    JobStatus,
    LogMessages,
    WebSocketMessage,
    WebSocketMessageType,
    WebSocketResponse,
)
from chat_ui.utils import get_client_ip, get_model_name, html_from_response

logger.remove()
logger.add(sink=sink)

if "pytest" in sys.modules:
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}
sqlite_url = f"sqlite:///{Config().db_path}"
engine = sqlmodel.create_engine(sqlite_url, echo=False, connect_args=connect_args)


def startup_check_outstanding_jobs(engine: sqlalchemy.engine.Engine) -> None:
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

    if Config().enable_do_bad_things_mode == "1":
        logger.warning("Do bad things mode is enabled!")

    if "pytest" not in sys.modules:
        # create all the tables
        sqlmodel.SQLModel.metadata.create_all(engine)
        migrate_database(engine)
        startup_check_outstanding_jobs(engine)

        t = BackgroundPoller(engine, get_model_name())
        t.start()
    logger.info("Prechecks done, starting app")

    # wait for FastAPI to do its thing
    yield

    if "pytest" not in sys.modules:
        logger.info("Shutting down app")
        t.message = "stop"
        t.join()


app = FastAPI(lifespan=lifespan)
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


@app.post(Urls.User)
async def post_user(
    request: Request,
    form: UserForm,
    session: Session = Depends(get_session),
) -> UserDetail:
    """post user"""
    newuser = Users(**form.model_dump())

    trace.get_current_span().set_attribute("userid", str(form.userid))
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
        # we're adding a new user
        session.add(newuser)
        session.commit()
        session.refresh(newuser)
        # create an initial session while we're here
        create_session(newuser.userid, session)

    res = UserDetail(
        userid=newuser.userid,
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

    trace.get_current_span().set_attribute("userid", str(job.userid))
    newjob = Jobs.from_newjobform(job, client_ip=client_ip)

    session.add(newjob)
    session.commit()
    session.refresh(newjob)
    logger.info(
        LogMessages.JobNew,
        src_ip=get_client_ip(request),
        **newjob.model_dump(round_trip=False, warnings=False),
    )
    trace.get_current_span().set_attribute("job_id", newjob.id)
    return Job.from_jobs(newjob, None)


@app.get(Urls.Jobs)
async def jobs(
    userid: UUID,
    sessionid: UUID | None = None,
    since: float | None = None,
    session: Session = Depends(get_session),
) -> List[Job]:
    """query the jobs for a given userid

    extra filters:

    - sessionid (a given chat session id)
    - since (a unix timestamp, only return jobs created/updated since this time)
    """

    trace.get_current_span().set_attribute("userid", str(userid))
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


@app.get(f"{Urls.Jobs}/{{userid}}/{{job_id}}")
async def job_detail(
    userid: UUID,
    job_id: UUID,
    session: Session = Depends(get_session),
) -> JobDetail:
    trace.get_current_span().set_attribute("userid", str(userid))
    trace.get_current_span().set_attribute("job_id", str(job_id))
    try:
        query = select(Jobs).where(Jobs.userid == userid, Jobs.id == job_id)
        job = session.exec(query).one()
        # convert the output into HTML
        # technically this'll be caught as an exception, but it doesn't hurt to be explicit
        if job is not None:
            if job.response is not None:
                job.response = html_from_response(job.response)
        else:
            raise HTTPException(404)
        session.reset()
        feedback = JobFeedback.get_feedback(session, job_id)
        return JobDetail.from_jobs(job, feedback)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Item not found")


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
                raw_msg = "<empty>"
                raw_msg = await websocket.receive_json()
                response = WebSocketResponse(
                    message=WebSocketMessageType.Error.value, payload="unknown message"
                )
                data = WebSocketMessage.model_validate(raw_msg)
            except WebSocketDisconnect:
                logger.debug(
                    LogMessages.WebsocketDisconnected, src_ip=get_client_ip(websocket)
                )
                return
            except Exception as error:

                logger.error(
                    LogMessages.WebsocketError.value,
                    error=error,
                    src_ip=get_client_ip(websocket),
                    raw_msg=raw_msg,
                )
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
    except WebSocketDisconnect:
        logger.debug(LogMessages.WebsocketDisconnected, src_ip=get_client_ip(websocket))
        return
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
        logger.error(LogMessages.WebsocketError, error=error)
        return


@app.get(Urls.HealthCheck)
async def healthcheck() -> str:
    """healthcheck endpoint"""
    return "OK"


@app.post(Urls.Analyse)
async def analyze(
    analyze_form: AnalyzeForm,
    session: Session = Depends(get_session),
) -> JobAnalysis:
    """analyse a prompt"""

    trace.get_current_span().set_attribute("userid", str(analyze_form.userid))
    trace.get_current_span().set_attribute("job_id", str(analyze_form.jobid))
    trace.get_current_span().set_attribute(
        "analysis_type", analyze_form.analysis_type.value
    )
    # check we have a userid and jobid matching the query
    query = select(Jobs).where(
        Jobs.userid == analyze_form.userid, Jobs.id == analyze_form.jobid
    )
    try:
        session.exec(query).one()
    except NoResultFound:
        raise HTTPException(status_code=404, detail="User or jobid not found")

    # create the analysis request
    job_analysis: JobAnalysis = JobAnalysis.from_analyzeform(analyze_form)
    session.add(job_analysis)
    session.commit()
    session.refresh(job_analysis)
    return job_analysis


def user_has_sessions(userid: UUID, session: Session) -> bool:
    query = select(func.count(ChatUiDBSession.sessionid)).where(  # type: ignore
        ChatUiDBSession.userid == userid
    )
    res = session.scalar(query)
    if res is None:
        return False
    return res > 0


def create_session(userid: UUID, session: Session) -> ChatUiDBSession:
    """create a new session"""
    new_session = ChatUiDBSession(userid=userid)
    session.add(new_session)
    session.commit()
    session.refresh(new_session)
    logger.info(LogMessages.SessionNew, **new_session.model_dump(mode="json"))
    return new_session


@app.post("/session/new/{userid}")
async def session_new(
    userid: UUID, session: Session = Depends(get_session)
) -> ChatUiDBSession:
    # check the userid exists
    trace.get_current_span().set_attribute("userid", str(userid))
    try:
        session.exec(select(Users).where(Users.userid == userid)).one()
    except NoResultFound:
        raise HTTPException(status_code=404, detail="User not found")

    # create the new entry in the db
    new_session = create_session(userid, session)

    logger.info(LogMessages.SessionNew, **new_session.model_dump(mode="json"))
    return new_session


@app.post("/session/{userid}/{sessionid}")
async def session_update(
    userid: UUID,
    sessionid: UUID,
    form: SessionUpdateForm,
    session: Session = Depends(get_session),
) -> ChatUiDBSession:

    trace.get_current_span().set_attribute("userid", str(userid))
    trace.get_current_span().set_attribute("sessionid", str(sessionid))

    try:
        chatsession = session.exec(
            select(ChatUiDBSession).where(
                ChatUiDBSession.userid == userid,
                ChatUiDBSession.sessionid == sessionid,
            )
        ).one()

    except NoResultFound:
        raise HTTPException(status_code=404, detail="Session not found")
    chatsession.name = form.name
    session.add(chatsession)
    session.commit()
    session.refresh(chatsession)
    logger.info(
        LogMessages.SessionUpdate,
        userid=userid,
        sessionid=sessionid,
        session_name=chatsession.name,
    )
    return chatsession


@app.get(f"{Urls.Sessions}/{{userid}}")
async def get_user_sessions(
    userid: UUID, create: bool = True, session: Session = Depends(get_session)
) -> Sequence[ChatUiDBSession]:
    # check the user exists first

    trace.get_current_span().set_attribute("userid", str(userid))
    try:
        session.exec(select(Users).where(Users.userid == userid)).one()
    except NoResultFound:
        logger.info("User not found when asking for sessions", userid=userid)
        raise HTTPException(status_code=404, detail="User not found")

    try:
        query = (
            select(ChatUiDBSession)
            .where(ChatUiDBSession.userid == userid)
            .order_by(ChatUiDBSession.created.desc())  # type: ignore
            # because desc isn't a method of datetime but it works in sqlalchemy
        )
        res: Sequence[ChatUiDBSession] = session.exec(query).all()

        # if there aren't any sessions, create one
        if len(res) == 0 and create:
            res = [create_session(userid, session)]
    except NoResultFound:
        res = [create_session(userid, session)]

    return res


@app.get(Urls.Analyses)
async def analyses(
    analysisid: Optional[UUID] = None,
    userid: Optional[UUID] = None,
    session: Session = Depends(get_session),
) -> List[JobAnalysis]:
    """
    Query the analysis sessions

    """

    if userid is not None:
        trace.get_current_span().set_attribute("userid", str(userid))
    if analysisid is not None:
        trace.get_current_span().set_attribute("analysisid", str(analysisid))
    query = select(JobAnalysis)
    if userid is not None:
        query = query.where(JobAnalysis.userid == userid)
    elif analysisid is not None:
        query = query.where(JobAnalysis.analysisid == analysisid)
    else:
        raise HTTPException(
            400, "No filters provided, please specify either userid or analysisid"
        )
    return [item for item in session.exec(query).all()]


@app.get(Urls.AdminSessions)
async def admin_sessions(
    admin_password: Annotated[str, Header()],
    userid: Optional[UUID] = None,
    session: Session = Depends(get_session),
) -> List[ChatUiDBSession]:
    """
    *** Requires the admin password to be set in config ***

    Query the sessions database.


    Extra filters:

    - userid (a given userid)

    """
    config = Config()
    if userid is not None:
        trace.get_current_span().set_attribute("userid", str(userid))
    if config.admin_password is None:
        raise HTTPException(500, "Admin password not available")

    if config.admin_password != admin_password:
        raise HTTPException(403, "Admin password incorrect")

    query = select(ChatUiDBSession)
    if userid is not None:
        query = query.where(ChatUiDBSession.userid == userid)
    return [item for item in session.exec(query).all()]


@app.get(Urls.AdminJobs)
async def admin_jobs(
    admin_password: Annotated[str, Header()],
    userid: Optional[UUID] = None,
    sessionid: Optional[UUID] = None,
    session: Session = Depends(get_session),
) -> List[Job]:
    """
    *** Requires the admin password to be set in config ***

    Query the jobs table, maybe filtering on a userid or sessionid.

    extra filters:

    - userid (a given userid)
    - sessionid (a given chat session id)
    """
    config = Config()

    if userid is not None:
        trace.get_current_span().set_attribute("userid", str(userid))
    if sessionid is not None:
        trace.get_current_span().set_attribute("sessionid", str(sessionid))

    if config.admin_password is None:
        raise HTTPException(500, "Admin password not available")

    if config.admin_password != admin_password:
        raise HTTPException(403, "Admin password incorrect")

    query = select(Jobs)
    if userid is not None:
        query = query.where(Jobs.userid == userid)
    if sessionid is not None:
        query = query.where(Jobs.sessionid == sessionid)
    return [Job.from_jobs(job, None) for job in session.exec(query).all()]


@app.get(Urls.AdminUsers)
async def admin_users(
    admin_password: Annotated[str, Header()],
    userid: Optional[UUID] = None,
    session: Session = Depends(get_session),
) -> List[Users]:
    """
    *** Requires the admin password to be set in config ***

    Query the users, maybe filtering on an userid


    """
    config = Config()

    if userid is not None:
        trace.get_current_span().set_attribute("userid", str(userid))

    if config.admin_password is None:
        raise HTTPException(500, "Admin password not available")

    if config.admin_password != admin_password:
        raise HTTPException(403, "Admin password incorrect")

    query = select(Users)
    if userid is not None:
        query = query.where(Users.userid == userid.hex)
    return [item for item in session.exec(query).all()]


@app.get(Urls.AdminAnalyses)
async def admin_analyses(
    admin_password: Annotated[str, Header()],
    analysisid: Optional[UUID] = None,
    userid: Optional[UUID] = None,
    session: Session = Depends(get_session),
) -> List[JobAnalysis]:
    """
    *** Requires the admin password to be set in config ***

    Query the users, maybe filtering on an userid


    """
    if userid is not None:
        trace.get_current_span().set_attribute("userid", str(userid))
    if analysisid is not None:
        trace.get_current_span().set_attribute("analysisid", str(analysisid))
    config = Config()

    if config.admin_password is None:
        raise HTTPException(500, "Admin password not available")

    if config.admin_password != admin_password:
        raise HTTPException(403, "Admin password incorrect")

    query = select(JobAnalysis)
    if userid is not None:
        query = query.where(JobAnalysis.userid == userid)
    if analysisid is not None:
        query = query.where(JobAnalysis.analysisid == analysisid)
    return [item for item in session.exec(query).all()]


@app.get("/")
async def index() -> HTMLResponse:
    """returns the contents of html/index.html as a HTMLResponse object"""
    return HTMLResponse(
        Path(os.path.join(os.path.dirname(__file__), "html/index.html")).read_bytes()
    )
