from datetime import UTC, datetime
from uuid import uuid4
import pytest
import requests
from sqlmodel import Session
from chat_ui.backgroundpoller import BackgroundPoller
from chat_ui.config import Config
from chat_ui.db import JobAnalysis, Jobs
from chat_ui.models import AnalysisType, RequestType
from . import get_test_session  # noqa: E402,F401


# @pytest.mark.asyncio()
def test_bgp_tasks(session: Session) -> None:
    """tests running a task"""

    # async with aiohttp.ClientSession() as client_session:
    url = Config().backend_url
    if url is None:
        pytest.skip("No backend url configured!")
    url = "/".join(url.split("/")[:-1])
    url = f"{url}/docs"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            pytest.skip("Backend is wrong")
    except Exception as error:
        pytest.skip(f"Failed to connect to backend for tests, skipping! {error=}")

    bgp = BackgroundPoller(engine=None, model_name="testing")  # type: ignore
    userid = uuid4()
    sessionid = uuid4()
    job = Jobs(
        userid=userid,
        sessionid=sessionid,
        client_ip="123.123.123.123",
        prompt="Hello world",
        request_type=RequestType.Plain,
    )
    bgp.process_prompt(job, session)
    job = Jobs(
        userid=userid,
        sessionid=sessionid,
        client_ip="123.123.123.123",
        prompt="Hello world",
        request_type=RequestType.PromptInjection,
    )
    bgp.process_prompt(job, session)


def test_log_JobAnalysis() -> None:
    testobject = JobAnalysis(
        jobid=uuid4(),
        userid=uuid4(),
        preprompt="what does this look like?",
        input_text="your credit card number is 12345",
        output_text="wow you asked for a credit card number, that's bad!",
        analysis_type=AnalysisType.PromptAndResponse,
        time=datetime.now(UTC),
    )

    testobject.log()
    testobject.model_dump(mode="json")
