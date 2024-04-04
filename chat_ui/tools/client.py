from enum import StrEnum
import json
import os
import sys
from typing import Any, Dict, Optional
from uuid import UUID
import click
import requests

from chat_ui.forms import NewJobForm, SessionUpdateForm, UserForm
from chat_ui.models import RequestType

# Usage:
# Environment variables
# CHATUI_TOOL_HOSTNAME: The hostname of the server
# CHATUI_TOOL_PORT: The port of the server


def make_url(hostname: str, port: int | str, skip_tls: bool) -> str:
    """create a url from the hostname and port"""
    if skip_tls:
        return f"http://{hostname}:{port}"
    return f"https://{hostname}:{port}"


@click.group()
def cli() -> None:
    pass


def create_or_update_user(
    base_url: str, userid: UUID, name: Optional[str] = None
) -> None:
    """create or update a user"""
    print(f"Creating or updating {userid=} {name=}", file=sys.stderr)
    payload = UserForm(userid=userid, name=name)
    res = requests.post(f"{base_url}/user", json=payload.model_dump(mode="json"))
    if res.status_code != 200:
        print(f"Failed to update user: {res.text}", file=sys.stderr)
        sys.exit(1)
    else:
        print("Successfully pushed user!", file=sys.stderr)
        return res.json()


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

    base_url = make_url(hostname, port, skip_tls)
    click.echo(f"Connecting to {base_url}")

    if userid is None:
        click.echo("You must provide a userid to push a user")
        return
    if name is None:
        click.echo("You must provide a name to push a user")
        return
    res = create_or_update_user(base_url, UUID(userid), UUID(name))
    print(json.dumps(res, indent=4))


class SessionCommands(StrEnum):
    New = "new"
    GetSessions = "get"
    Update = "update"


def foo(help: int) -> None:
    print(help)


def create_session(base_url: str, userid: UUID) -> Dict[str, Any]:
    """create a session"""
    res = requests.post(f"{base_url}/session/new/{userid}")
    if res.status_code != 200:
        print(f"Failed to create new session: {res.text}", file=sys.stderr)
        sys.exit(1)
    else:
        if len(res.json()) == 0:
            print("No sessions found", file=sys.stderr)
            sys.exit(1)
        else:
            print("Got a new session!", file=sys.stderr)
            print(json.dumps(res.json(), indent=4))
            return res.json()


def update_session(
    base_url: str, name: str, sessionid: UUID, userid: UUID
) -> Dict[str, Any]:
    """update a session"""

    payload = SessionUpdateForm(name=name)
    res = requests.post(
        f"{base_url}/session/{userid}/{sessionid}",
        json=payload.model_dump(mode="json"),
    )
    if res.status_code != 200:
        click.echo(f"Failed to update session: {res.text}")
        sys.exit(1)
    else:
        print("Successfully updated session!")
        print(json.dumps(res.json(), indent=4))
        return res.json()


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
    sessionid: Optional[UUID] = None,
) -> None:
    base_url = make_url(hostname, port, skip_tls)

    try:
        command = SessionCommands(command)
    except ValueError:
        click.echo(f"Invalid command '{command}'", err=True)
        sys.exit(1)

    click.echo(f"Connecting to {base_url} with userid {userid}, {command=}", err=True)

    if command == SessionCommands.New:
        create_session(base_url, userid)
    elif command == SessionCommands.GetSessions:
        res = requests.get(f"{base_url}/sessions/{userid}", params={"create": False})
        if res.status_code != 200:
            click.echo(f"Failed to get sessions: {res.text}")
            sys.exit(1)
        else:
            if len(res.json()) == 0:
                print("No sessions found", file=sys.stderr)
                return
            else:
                print("Got sessions!", file=sys.stderr)
                print(json.dumps(res.json(), indent=4))
    elif command == SessionCommands.Update:
        if name is None:
            click.echo("You must provide a name to update a session", err=True)
            sys.exit(1)
        if sessionid is None:
            click.echo("You must provide a sessionid to update a session", err=True)
            sys.exit(1)

        update_session(base_url, sessionid, name, userid)


class JobCommands(StrEnum):
    Get = "get"
    Create = "create"


def create_job(base_url: str, payload: NewJobForm) -> Dict[str, Any]:
    """push a job"""
    res = requests.post(f"{base_url}/job", json=payload.model_dump(mode="json"))
    if res.status_code != 200:
        print(f"Failed to create job: {res.text}", file=sys.stderr)
        sys.exit(1)
    else:
        print("Successfully created job!")
        return res.json()


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

    base_url = make_url(hostname, port, skip_tls)
    click.echo(f"Connecting to {base_url} with userid {userid}", err=True)

    if command == JobCommands.Get:
        params = {"userid": userid.hex}
        if sessionid is not None:
            params["sessionid"] = sessionid
        res = requests.get(f"{base_url}/jobs", params=params)
        if res.status_code != 200:
            click.echo(f"Failed to get jobs: {res.text}")
            sys.exit(1)
        else:
            if len(res.json()) == 0:
                print("No jobs found")
                return
            else:
                print("Got jobs!")
                for job in res.json():
                    print(json.dumps(job, indent=4))
    elif command == JobCommands.Create:
        if prompt is None:
            click.echo("You must provide a prompt to create a job", err=True)
            sys.exit(1)
        if sessionid is None:
            click.echo("You must provide a sessionid to create a job", err=True)
            sys.exit(1)

        click.echo(f"Creating a new job for userid {userid}", err=True)
        payload = NewJobForm(
            prompt=prompt,
            sessionid=sessionid,
            userid=userid,
            request_type=RequestType.Plain,
        )
        res = create_job(base_url, payload)
        print(json.dumps(res, indent=4))


if __name__ == "__main__":
    cli()
