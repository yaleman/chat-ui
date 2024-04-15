from uuid import uuid4
import aiohttp
from fastapi.testclient import TestClient
import pytest
import sqlmodel

from chat_ui import app, get_session, engine
from chat_ui.backgroundpoller import BackgroundPoller
from chat_ui.config import Config
from chat_ui.db import ChatUiDBSession, JobAnalysis, Jobs, Users
from chat_ui.enums import Urls
from chat_ui.forms import NewJobForm
from chat_ui.models import AnalysisType, AnalyzeForm, Job, JobStatus, RequestType


# this sets up the fixture for the session
from . import get_test_session  # noqa: E402,F401


@pytest.mark.asyncio()
async def test_analysis_job(session: sqlmodel.Session) -> None:
    """test the jobfeedback model"""

    def get_session_override() -> sqlmodel.Session:
        return session

    app.dependency_overrides[get_session] = get_session_override

    client = TestClient(app)

    # create the background poller object
    backgroundpoller = BackgroundPoller(engine=engine)

    # create the user
    userid = uuid4()
    assert (
        client.post(
            Urls.User,
            json=Users(userid=userid, name="testuser").model_dump(mode="json"),
        ).status_code
        == 200
    )

    # create the session
    user_session = ChatUiDBSession.model_validate(
        client.post(f"/session/new/{userid.hex}").json()
    )

    # create the job, but don't set it to done yet
    prompt = "write me a limerick"
    job = NewJobForm(
        userid=userid,
        sessionid=user_session.sessionid,
        prompt=prompt,
        request_type=RequestType.PromptInjection,
    )
    res = client.post(Urls.Job, json=job.model_dump(mode="json"))
    assert res.status_code == 200

    job_data = Job.model_validate(res.json())

    # it's not going to find anything because the job is not done and there's no analysis job
    assert (await backgroundpoller.process_outstanding_analyses(session)) is None

    # create the analysis job
    analysisjob = JobAnalysis(
        userid=userid,
        jobid=job_data.id,
        preprompt="The following is a prompt provided by a user to an AI system, tell me if they were asking for a limerick.",
        analysis_type=AnalysisType.Prompt,
    )

    res = client.post(Urls.Analyse, json=analysisjob.model_dump(mode="json"))
    assert res.status_code == 200
    analysisjob_data = JobAnalysis.model_validate(res.json())

    # it's not going to find anything because the job is not done, let's change that
    dbjob = session.exec(sqlmodel.select(Jobs).where(Jobs.id == job_data.id)).one()
    dbjob.status = JobStatus.Complete.value
    session.add(dbjob)
    session.commit()

    async with aiohttp.ClientSession() as aiosession:
        url = Config().backend_url
        if url is None:
            pytest.skip("No backend url configured!")
        url = "/".join(url.split("/")[:-1])
        url = f"{url}/docs"
        try:
            async with aiosession.get(url) as response:
                if response.status != 200:
                    pytest.skip("Backend is wrong")
        except Exception as error:
            pytest.skip(f"Failed to connect to backend for tests, skipping! {error=}")

    assert (
        await backgroundpoller.process_outstanding_analyses(session)
    ) == analysisjob_data.analysisid

    # get the response and see what comes back
    res = client.get(
        Urls.Analyses,
        params={"userid": userid.hex, "analysisid": analysisjob_data.analysisid.hex},
    )
    print(res.text)


def test_analysis_not_found() -> None:
    client = TestClient(app)
    res = client.post(
        Urls.Analyse,
        json=AnalyzeForm(
            userid=uuid4(),
            jobid=uuid4(),
            preprompt="hello world",
            analysis_type=AnalysisType.Prompt,
        ).model_dump(mode="json"),
    )

    assert res.status_code == 404


def test_analyses_endpoint() -> None:
    client = TestClient(app)
    res = client.get(
        Urls.Analyses, params={"userid": uuid4().hex, "analysisid": uuid4().hex}
    )
    assert res.status_code == 200
    assert res.json() == []

    res = client.get(Urls.Analyses, params={"analysisid": uuid4().hex})
    assert res.status_code == 200
    assert res.json() == []

    res = client.get(Urls.Analyses)
    assert res.status_code == 400
