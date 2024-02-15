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

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)
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
from starlette.middleware.sessions import SessionMiddleware
from chat_ui.backgroundpoller import BackgroundPoller
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


class AppState:
    """keeps internal state"""

    def __init__(
        self,
        db_path: Optional[str] = None,
    ) -> None:

        self.config = Config()

        if db_path is not None:
            self.config.db_path = db_path

        backend_api_key = self.config.backend_api_key or "not needed"
        self.backend_client = OpenAI(
            base_url=self.config.backend_url, api_key=backend_api_key
        )

        self.db = DB(self.config.db_path)
        if self.config.backend_url is None:
            logger.error(
                "No backend_url set, no point running! Set the {}BACKEND_URL environment variable!",
                self.config.model_config.get("env_prefix"),
            )
            sys.exit(1)

        logger.debug(self.config.model_dump())

    async def handle_job(self, job: Job) -> None:
        """does the background job handling bit"""

        try:
            job.status = "running"
            jobdetail = JobDetail(**job.model_dump())
            self.db.update_job(jobdetail)
            # ok, let's do the prompty thing

            history = (
                ChatCompletionSystemMessageParam(
                    role="system", content=self.config.backend_system_prompt
                ),
                ChatCompletionUserMessageParam(role="user", content=jobdetail.prompt),
            )
            logger.debug("Starting job: {}", job)
            start_time = datetime.utcnow().timestamp()
            # TODO: start the timer
            completion = self.backend_client.chat.completions.create(
                model="local-model",  # this field is currently unused
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
            jobdetail.runtime = datetime.utcnow().timestamp() - start_time
            job_metadata = {
                "model": completion.model,
                "usage": usage,
            }
            logger.debug("Job metadata: {}", json.dumps(job_metadata))
            jobdetail.response = response
            jobdetail.metadata = json.dumps(job_metadata, default=str)
            jobdetail.status = "complete"
            self.db.update_job(jobdetail)
        except Exception as error:
            logger.error("id={} error={}", job.id, error)
            self.db.error_job(job, str(error))


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
    if res is None:
        raise HTTPException(status_code=404, detail="Item not found")
    logger.debug(res.model_dump_json())
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
