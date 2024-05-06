from enum import StrEnum
import json
import os
import sys
from typing import Any, Dict, List, Optional
from uuid import UUID
import click
from loguru import logger
import requests

from chat_ui.db import ChatUiDBSession, JobAnalysis, Users
from chat_ui.enums import Urls
from chat_ui.forms import NewJobForm, SessionUpdateForm, UserForm
from chat_ui.models import AnalysisType, AnalyzeForm, Job, JobDetail, RequestType

# Usage:
# Environment variables
# CHATUI_TOOL_HOSTNAME: The hostname of the server
# CHATUI_TOOL_PORT: The port of the server


def make_url(hostname: str, port: int | str, skip_tls: bool) -> str:
    """create a url from the hostname and port"""
    if skip_tls:
        return f"http://{hostname}:{port}"
    return f"https://{hostname}:{port}"


class ChatUIClient:

    def __init__(
        self,
        hostname: str,
        port: int,
        skip_tls: bool = False,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = make_url(hostname, port, skip_tls)
        self.hostname = hostname
        self.port = port
        self.skip_tls = skip_tls
        self.session: Optional[requests.Session] = session

    def _get_session(self) -> requests.Session:
        """get a requests session"""
        if self.session is not None:
            return self.session
        session = requests.Session()
        if self.skip_tls:
            session.verify = False
        self.session = session
        return session

    def get_jobs(
        self,
        userid: Optional[UUID] = None,
        sessionid: Optional[UUID] = None,
        session: Optional[requests.Session] = None,
        admin_password: Optional[str] = None,
    ) -> List[Job]:
        """get jobs"""
        if session is None:
            session = self._get_session()
        params = {}
        if userid is not None:
            params["userid"] = userid.hex
        if sessionid is not None:
            params["sessionid"] = sessionid.hex
        headers = {}
        if admin_password is None:
            url = f"{self.base_url}{Urls.Jobs}"
            if not params:
                raise ValueError("You need to specify a userid or admin password!")
        else:
            url = f"{self.base_url}{Urls.AdminJobs}"
            headers = self._admin_header(admin_password)
        res = session.get(url, params=params, headers=headers)
        if res.status_code != 200:
            logger.error(f"Failed to get jobs: {res.text}")
            return []
        else:
            return [Job.model_validate(job) for job in res.json()]

    def get_job(
        self, userid: UUID, jobid: UUID, session: Optional[requests.Session] = None
    ) -> JobDetail:
        """get an individual job"""
        if session is None:
            session = self._get_session()

        res = session.get(f"{self.base_url}{Urls.Jobs}/{userid}/{jobid}")
        res.raise_for_status()
        return JobDetail.model_validate(res.json())

    def create_or_update_user(
        self,
        userid: UUID,
        name: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> Dict[str, Any]:
        """create or update a user"""
        if session is None:
            session = self._get_session()

        logger.info(f"Creating or updating {userid=} {name=}", file=sys.stderr)
        payload = UserForm(userid=userid, name=name)
        res = session.post(
            f"{self.base_url}/user", json=payload.model_dump(mode="json")
        )
        if res.status_code != 200:
            print(f"Failed to update user: {res.text}", file=sys.stderr)
            sys.exit(1)
        else:
            logger.info("Successfully pushed user!", file=sys.stderr)
            result: Dict[str, Any] = res.json()
            return result

    def create_session(
        self, userid: UUID, session: Optional[requests.Session] = None
    ) -> Optional[ChatUiDBSession]:
        """create a session"""
        if session is None:
            session = self._get_session()

        res = session.post(f"{self.base_url}/session/new/{userid}")
        if res.status_code != 200:
            logger.error(f"Failed to create new session: {res.text}")
            raise Exception("Failed to create new session")
        else:
            if len(res.json()) == 0:
                return None
            else:
                # logger.debug("Got a new session!")
                # logger.info(json.dumps(res.json(), indent=4))
                return ChatUiDBSession.model_validate(res.json())

    def update_session(
        self,
        name: str,
        sessionid: UUID,
        userid: UUID,
        session: Optional[requests.Session] = None,
    ) -> Optional[ChatUiDBSession]:
        """update a session"""
        if session is None:
            session = self._get_session()

        payload = SessionUpdateForm(name=name)
        res = session.post(
            f"{self.base_url}/session/{userid}/{sessionid}",
            json=payload.model_dump(mode="json"),
        )
        if res.status_code != 200:
            logger.error(f"Failed to update session: {res.text}")
            # sys.exit(1)
            return None
        else:
            logger.debug("Successfully updated session!")
            logger.info(json.dumps(res.json(), indent=4))
            return ChatUiDBSession.model_validate(res.json())

    def get_sessions(
        self,
        userid: Optional[UUID] = None,
        session: Optional[requests.Session] = None,
        admin_password: Optional[str] = None,
    ) -> List[ChatUiDBSession]:
        """get sessions"""
        if session is None:
            session = self._get_session()

        headers = {}

        if admin_password is None:
            url = f"{self.base_url}/sessions/{userid}?create=False"
            if userid is None:
                raise ValueError("You need to specify a userid or admin password!")
            params = {}
        else:
            url = f"{self.base_url}{Urls.AdminSessions.value}"
            params = {"userid": userid.hex} if userid is not None else {}
            headers = self._admin_header(admin_password)

        res = session.get(
            url,
            headers=headers,
            params=params,
        )

        if res.status_code != 200:
            logger.error(f"Failed to get sessions: {res.text}")
            return []
        else:
            if len(res.json()) == 0:
                logger.warning("No sessions found", file=sys.stderr)
                return []
            else:

                return [
                    ChatUiDBSession.model_validate(session) for session in res.json()
                ]

    def create_job(
        self,
        prompt: str,
        sessionid: UUID,
        userid: UUID,
        request_type: RequestType = RequestType.Plain,
        session: Optional[requests.Session] = None,
    ) -> Optional[Job]:
        """push a job"""

        if session is None:
            session = self._get_session()

        payload = NewJobForm(
            prompt=prompt,
            sessionid=sessionid,
            userid=userid,
            request_type=request_type,
        )
        res = session.post(
            f"{self.base_url}{Urls.Job}", json=payload.model_dump(mode="json")
        )
        if res.status_code != 200:
            logger.error("Failed to create job: {}", res.text)
            return None
        logger.success("Successfully created job!")

        return Job.model_validate(res.json())

    def get_users(
        self,
        admin_password: str,
        userid: Optional[UUID] = None,
        session: Optional[requests.Session] = None,
    ) -> List[Users]:
        """gets the users from the system, is an admin-only endpoint currently"""
        headers = self._admin_header(admin_password)

        params = {"userid": userid.hex} if userid is not None else {}

        if session is None:
            session = self._get_session()
        res = session.get(
            f"{self.base_url}{Urls.AdminUsers}", headers=headers, params=params
        )
        if res.status_code != 200:
            logger.error(f"Failed to get users: {res.text}")
            return []
        else:
            result: List[Users] = [Users.model_validate(user) for user in res.json()]
            return result

    def get_analyses(
        self,
        admin_password: Optional[str] = None,
        analysisid: Optional[UUID] = None,
        userid: Optional[UUID] = None,
        session: Optional[requests.Session] = None,
    ) -> List[JobAnalysis]:
        """Get the analyses, pass the admin password if you want to get everything"""
        if session is None:
            session = self._get_session()
        params = {}
        if userid is not None:
            params["userid"] = userid.hex
        if analysisid is not None:
            params["analysisid"] = analysisid.hex

        if admin_password is None:
            url = f"{self.base_url}{Urls.Analyses}"
            headers = {}
            if not params:
                raise ValueError(
                    "You need to specify a userid or analysisid to get analyses as a non-admin!"
                )
        else:
            url = f"{self.base_url}{Urls.AdminAnalyses}"
            headers = self._admin_header(admin_password)

        res = session.get(url=url, headers=headers, params=params)
        if res.status_code != 200:
            logger.error(f"Failed to get analyses: {res.text}")
            return []
        else:
            result: List[JobAnalysis] = [
                JobAnalysis.model_validate(analysis) for analysis in res.json()
            ]
            return result

    @classmethod
    def _admin_header(cls, admin_password: str) -> dict[str, str]:
        """return an admin header"""
        return {"admin-password": admin_password}

    def create_analysis(
        self,
        userid: UUID,
        jobid: UUID,
        analysis_type: AnalysisType,
        preprompt: str,
        session: Optional[requests.Session] = None,
    ) -> JobAnalysis:
        """create an analysis job in the backend"""
        if session is None:
            session = self._get_session()

        url = f"{self.base_url}{Urls.Analyse}"
        payload = AnalyzeForm(
            jobid=jobid, userid=userid, analysis_type=analysis_type, preprompt=preprompt
        )

        res = session.post(url, json=payload.model_dump(mode="json"))
        res.raise_for_status()

        return JobAnalysis.model_validate(res.json())


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--userid", "-u", help="The userid of the user")
@click.option("--name", "-n", help="The name of the user")
@click.option(
    "--hostname",
    default=os.getenv("CHATUI_TOOL_HOSTNAME", "localhost"),
    help="The hostname of the server",
)
@click.option(
    "--port",
    default=os.getenv("CHATUI_TOOL_PORT", "9195"),
    help="The port of the server",
)
@click.option("--skip-tls", "-S", is_flag=True, help="Connect to HTTP")
def user(
    userid: Optional[UUID] = None,
    name: Optional[str] = None,
    skip_tls: bool = False,
    port: str = os.getenv("CHATUI_TOOL_PORT", "9195"),
    hostname: str = os.getenv("CHATUI_TOOL_HOSTNAME", "localhost"),
) -> None:
    """user management things"""

    if userid is None:
        click.echo("You must provide a userid to push a user")
        return
    if name is None:
        click.echo("You must provide a name to push a user")
        return

    client = ChatUIClient(hostname, int(port), skip_tls)
    res = client.create_or_update_user(userid, name)
    print(json.dumps(res, indent=4))


class SessionCommands(StrEnum):
    New = "new"
    GetSessions = "get"
    Update = "update"


def foo(help: int) -> None:
    print(help)


@cli.command()
@click.argument("command")
@click.argument("userid")
@click.option(
    "--name",
    help="The new name of the session",
)
@click.option(
    "--sessionid",
    help="The session (UU)ID of the session",
)
@click.option(
    "--hostname",
    default=os.getenv("CHATUI_TOOL_HOSTNAME", "localhost"),
    help="The hostname of the server",
)
@click.option(
    "--port", default=os.getenv("CHATUI_TOOL_PORT", 9195), help="The port of the server"
)
@click.option("--skip-tls", "-S", is_flag=True, help="Connect to HTTP")
def session(
    command: SessionCommands,
    userid: str,
    hostname: str,
    port: int,
    skip_tls: bool = False,
    name: Optional[str] = None,
    sessionid: Optional[str] = None,
) -> None:

    try:
        command = SessionCommands(command)
    except ValueError:
        click.echo(f"Invalid command '{command}'", err=True)
        sys.exit(1)

    click.echo(f"Connecting  with userid {userid}, {command=}", err=True)

    client = ChatUIClient(hostname, port, skip_tls)

    if command == SessionCommands.New:
        client.create_session(UUID(userid))
    elif command == SessionCommands.GetSessions:
        client.get_sessions(UUID(userid))
    elif command == SessionCommands.Update:
        if name is None:
            click.echo("You must provide a name to update a session", err=True)
            sys.exit(1)
        if sessionid is None:
            click.echo("You must provide a sessionid to update a session", err=True)
            sys.exit(1)

        client.update_session(
            name=sessionid, sessionid=UUID(sessionid), userid=UUID(userid)
        )


class JobCommands(StrEnum):
    Get = "get"
    Create = "create"


@cli.command()
@click.argument("command", default="get")
@click.argument("userid")
@click.option(
    "--hostname",
    default=os.getenv("CHATUI_TOOL_HOSTNAME", "localhost"),
    help="The hostname of the server",
)
@click.option(
    "--port", default=os.getenv("CHATUI_TOOL_PORT", 9195), help="The port of the server"
)
@click.option("--skip-tls", "-S", is_flag=True, help="Connect to HTTP")
@click.option("--prompt", help="The prompt for the job")
@click.option("--sessionid", help="The sessionid for the job")
def job(
    userid: UUID,
    skip_tls: bool = False,
    command: str = "get",
    port: str = os.getenv("CHATUI_TOOL_PORT", "9195"),
    hostname: str = os.getenv("CHATUI_TOOL_HOSTNAME", "localhost"),
    prompt: Optional[str] = None,
    sessionid: Optional[str] = None,
) -> None:
    """jobs management"""

    try:
        command = JobCommands(command)
    except ValueError:
        click.echo(f"Invalid command '{command}'")
        sys.exit(1)

    client = ChatUIClient(hostname, int(port), skip_tls)

    logger.error(f"Connecting to {client.base_url} with userid {userid}")

    if command == JobCommands.Get:
        if sessionid is not None:
            p_sessionid = UUID(sessionid)
        res = client.get_jobs(userid, p_sessionid)
        if not res:
            click.echo(f"Failed to get jobs: {res}")
            sys.exit(1)
        else:
            if len(res) == 0:
                logger.debug("No jobs found")
                return
            else:
                logger.debug("Got jobs!")
                for job in res:
                    print(json.dumps(job, indent=4))
    elif command == JobCommands.Create:
        if prompt is None:
            click.echo("You must provide a prompt to create a job", err=True)
            sys.exit(1)
        if sessionid is None:
            click.echo("You must provide a sessionid to create a job", err=True)
            sys.exit(1)

        click.echo(f"Creating a new job for userid {userid}", err=True)

        result = client.create_job(
            prompt=prompt,
            sessionid=UUID(sessionid),
            userid=userid,
            request_type=RequestType.Plain,
        )
        print(json.dumps(result, indent=4))


if __name__ == "__main__":
    cli()
