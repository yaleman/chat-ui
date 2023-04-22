""" chat emulator using fastapi """

from datetime import datetime
import json
import os
import os.path
import random
import string
from pathlib import Path

from typing import Annotated, Dict, List, Tuple
from fortune import fortune # type: ignore
from fastapi import FastAPI, HTTPException, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware

SAVE_TIMER = 1

SUPERSECRETREQUEST = os.getenv("SUPERSECRETREQUEST", "hello world").split()
SUPERSECRETFLAG = os.getenv("SUPERSECRETFLAG", "TheCheeseIsALie")

# type for interactions
INTERACTION = Tuple[float, str, str]

class AppState:
    """ keeps internal state """
    def __init__(self, history_file: str = "history.json", max_history_age: int=3600) -> None:
        self.sessions: Dict[str, List[INTERACTION]] = {}
        self.history_file = history_file
        self.load_history()
        self.last_save = -1.0
        self.max_history_age = max_history_age


    def record_message(self, session_id: str, interaction: INTERACTION) -> None:
        """ records a message for a session """
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        self.sessions[session_id].append(interaction)
        self.save_history()

    def get_history(self, session_id: str) -> List[INTERACTION]:
        """ returns the history for a session """
        if session_id not in self.sessions:
            self.sessions[session_id] = []
        response = self.sessions[session_id]
        # sort on the timestamp
        response.sort(key=lambda x: x[0], reverse=True)
        return response

    def trim_history(self) -> None:
        """ goes through the self.sessions and removes things older than self.max_history seconds old """
        for session_id in self.sessions:
            self.sessions[session_id] = [interaction
                                         for interaction
                                         in self.sessions[session_id]
                                         if interaction[0] > datetime.utcnow().timestamp() - self.max_history_age]

    def clear_history(self, session_id: str) -> None:
        """ clears the data for this session """
        print(f"Clearing history for {session_id}")
        self.sessions[session_id] = []
        self.save_history()

    def save_history(self) -> None:
        """ if self.last_save is more than 10 seconds ago, save the history to a file """
        self.trim_history()
        if datetime.utcnow().timestamp() > self.last_save + SAVE_TIMER:
            history = Path(self.history_file)
            history.write_text(json.dumps(self.sessions, default=str, ensure_ascii=False))
            self.last_save = datetime.utcnow().timestamp()

    def load_history(self) -> None:
        """ loads the history from a file """
        history = Path(self.history_file)
        if history.exists():
            self.sessions = json.loads(history.read_text())


state = AppState()

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=random.sample(string.ascii_letters + string.digits, 32),
    session_cookie="chatsession",
    )

@app.post("/clear")
async def clear(request: Request) -> HTMLResponse:
    """ clears the message history """
    request.session.setdefault("chatsession", "".join(random.sample(
            string.ascii_letters + string.digits, 32)))
    state.clear_history(request.session["chatsession"])
    response = HTMLResponse("")
    response.set_cookie("chatsession", request.session["chatsession"])
    return response

def generate_response_boxes(interactions: List[INTERACTION]) -> HTMLResponse:
    """ generates the response boxes """
    return HTMLResponse("\n".join([ f"""<div class='message'
    data-bs-toggle="tooltip" data-bs-placement="bottom" title=\"{interaction[0]}\">{interaction[1]}</div>
    <div class=\"response\">{interaction[2]}</div>"""
            for interaction
            in interactions]))

@app.get("/history")
async def history(request: Request) -> HTMLResponse:
    """ gets the message history """
    request.session.setdefault("chatsession", "".join(random.sample(
            string.ascii_letters + string.digits, 32)))
    response = generate_response_boxes(state.get_history(request.session["chatsession"]))
    response.set_cookie("chatsession", request.session["chatsession"])
    return response

@app.post("/chat")
async def chat(message: Annotated[str, Form()], request: Request) -> HTMLResponse:
    """ chat post endpoint """
    request.session.setdefault("chatsession", "".join(random.sample(
            string.ascii_letters + string.digits, 32)))
    if message.strip() != "":
        chat_response = f"You win! Here is the flag: {SUPERSECRETFLAG}"
        splitmsg = message.lower().strip().split()
        for word in SUPERSECRETREQUEST:
            if word not in splitmsg:
                fortune_text = fortune().replace("\n", "<br />")\
                    .replace("\r", "").replace("\t", "")
                chat_response = fortune_text
                break
        state.record_message(request.session["chatsession"], (datetime.utcnow().timestamp(), message, chat_response))
    response = generate_response_boxes(state.get_history(request.session["chatsession"]))
    response.set_cookie("chatsession", request.session["chatsession"])
    return response

@app.get("/img/{filename}")
async def img(filename: str) -> FileResponse:
    """ returns the contents of html/index.html as a HTMLResponse object """
    imgfile = Path(os.path.join(os.path.dirname(__file__), "img/", filename))
    if not imgfile.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    return FileResponse(imgfile)

@app.get("/css/{filename}")
async def css(filename: str) -> FileResponse:
    """ returns the contents of html/index.html as a HTMLResponse object """
    cssfile = Path(os.path.join(os.path.dirname(__file__), "css/", filename))
    if not cssfile.exists():
        raise HTTPException(status_code=404, detail="Item not found")
    return FileResponse(cssfile)

@app.get("/")
async def index() -> HTMLResponse:
    """ returns the contents of html/index.html as a HTMLResponse object """
    htmlfile = os.path.join(os.path.dirname(__file__), "html/index.html")
    return HTMLResponse(open(htmlfile).read())