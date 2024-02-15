""" chat emulator using fastapi """

from contextlib import asynccontextmanager
import os
import os.path
import random
import string
from pathlib import Path
import threading
import time

from typing import Any, AsyncGenerator, List, Optional, Tuple
from fastapi import (
    FastAPI,
    HTTPException,
    BackgroundTasks,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger
import requests
from starlette.middleware.sessions import SessionMiddleware
from chat_ui.config import Config
from chat_ui.db import DB

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

SAVE_TIMER = 1

SUPERSECRETREQUEST = os.getenv("SUPERSECRETREQUEST", "hello world").split()
SUPERSECRETFLAG = os.getenv("SUPERSECRETFLAG", "TheCheeseIsALie")

# type for interactions
INTERACTION = Tuple[float, str, str]


class BackgroundPoller(threading.Thread):
    def __init__(self, shared_message: str = "run"):
        super().__init__()
        self.config = Config()
        self.shared_message = shared_message

    def run(self) -> None:
        if self.config.backend_url is None:
            logger.info("No backend_url set, not starting background poller")
            return
        logger.debug(
            "Starting background poller on backend_url={}", self.config.backend_url
        )
        loops = 0
        while True:
            # shutdown handler
            if self.shared_message == "stop":
                logger.info("Shutting down background poller")
                break
            loops += 1
            if loops == 5:
                loops = 0
                try:

                    test_url = f"{self.config.backend_url}/v1/models"
                    res = requests.get(test_url, timeout=1)
                    res.raise_for_status()
                    logger.debug("Backend {} is up!", test_url)
                except Exception as error:
                    logger.error(
                        "Failed to query backend test_url={} error={}", test_url, error
                    )
            time.sleep(1)


class AppState:
    """keeps internal state"""

    def __init__(
        self,
        # history_file: str = "history.json",
        db_path: Optional[str] = None,
        # max_history_age: int = 3600,
    ) -> None:

        self.config = Config()

        if db_path is not None:
            self.config.db_path = db_path

        logger.debug(self.config.model_dump())

        self.db = DB(self.config.db_path)

    async def handle_job(self, job: Job) -> None:
        """does the background job handling bit"""
        job = JobDetail(**job.model_dump())
        logger.debug("Starting job: {}", job)

        job.status = "running"
        self.db.update_job(job)

        try:
            raise ValueError("lol")
        except Exception as error:
            logger.error("id={} error={}", job.id, error)
            self.db.error_job(job)


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, Any]:
    t = BackgroundPoller()
    t.start()
    yield
    t.shared_message = "stop"


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=random.sample(string.ascii_letters + string.digits, 32),
    session_cookie="chatsession",
)


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
async def post_user(form: UserForm) -> UserDetail:
    """post user"""
    user = state.db.create_user(form)
    if user is not None:
        logger.info(user.model_dump_json())
        return user
    raise HTTPException(status_code=500, detail="Failed to create user")


@app.post("/job")
async def create_job(job: NewJob, background_tasks: BackgroundTasks) -> Job:
    logger.info("Got new job: {}", job)
    res = state.db.create_job(job)
    background_tasks.add_task(
        state.handle_job, JobDetail(prompt=job.prompt, **res.model_dump())
    )
    return res


@app.get("/jobs")
async def jobs(userid: str) -> List[Job]:
    """query the jobs for a given userid"""
    return state.db.get_jobs(userid)


@app.get("/jobs/{userid}/{job_id}")
async def job_detail(userid: str, job_id: str) -> JobDetail:
    res = state.db.get_job(userid, job_id)
    logger.debug(res)
    if res is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return res


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
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
                        response = WebSocketResponse(
                            message="jobs", payload=state.db.get_jobs(data.userid)
                        )
                    except Exception as error:
                        logger.error(
                            "websocket error={} ip={}", error, websocket.client.host
                        )
                        continue

                elif data.message == "delete":
                    if data.payload is not None:
                        id = validate_uuid(data.payload)
                        res = state.db.hide_job(userid=data.userid, id=id)
                        if res is not None:
                            payload = res.model_dump_json()
                        else:
                            payload = ""
                        response = WebSocketResponse(message="delete", payload=payload)
                    else:
                        response = WebSocketResponse(
                            message="error",
                            payload="no ID specified when asking for delete!",
                        )
            except Exception as error:
                logger.error("websocket error={} ip={}", error, websocket.client.host)
                response = WebSocketResponse(message="error", payload=str(error))
            logger.debug(
                "websocket ip={} msg={}",
                websocket.client.host,
                response.as_message(),
            )
            await websocket.send_text(response.as_message())
    except WebSocketDisconnect as disconn:
        logger.debug(
            "websocket disconnected ip={} msg={}", websocket.client.host, disconn
        )
    except Exception as error:
        logger.error("websocket error={} ip={}", error, websocket.client.host)


@app.get("/")
async def index() -> HTMLResponse:
    """returns the contents of html/index.html as a HTMLResponse object"""
    htmlfile = os.path.join(os.path.dirname(__file__), "html/index.html")
    return HTMLResponse(open(htmlfile).read())
