import os
from uuid import uuid4

import pytest
from chat_ui.backgroundpoller import BackgroundJob
from chat_ui.db import Jobs
from chat_ui.models import Job, JobDetail, JobStatus, RequestType, WebSocketMessage

os.environ["CHATUI_BACKEND_URL"] = "test"


def test_websocketmessage() -> None:
    """test parsing"""
    with pytest.raises(ValueError):
        WebSocketMessage.model_validate({"userid": "foobar", "message": "jobs"})
    with pytest.raises(ValueError):
        WebSocketMessage.model_validate({"userid": uuid4().hex, "message": "test"})


def test_jobstatus() -> None:
    with pytest.raises(ValueError):
        JobStatus("foobar")
    JobStatus("created")


def test_requestype() -> None:
    with pytest.raises(ValueError):
        RequestType("foobar")
    RequestType("plain")


def test_jobdetail_from_jobs() -> None:
    """tests converting from `Jobs` to `JobDetail`"""
    sessionid = uuid4()
    userid = uuid4()
    id = uuid4()
    jobs = Jobs(
        id=id,
        client_ip="1.2.3.4",
        sessionid=sessionid,
        userid=userid,
        request_type=RequestType.DOS.value,
        prompt="hello world",
    )

    jobdetail = JobDetail.from_jobs(jobs, None)
    assert jobdetail.sessionid == sessionid
    assert jobdetail.prompt == "hello world"
    assert jobdetail.id == id


def test_job_from_jobs() -> None:
    """test converting from Jobs to Job"""
    sessionid = uuid4()
    userid = uuid4()
    id = uuid4()
    jobs = Jobs(
        id=id,
        client_ip="1.2.3.4",
        sessionid=sessionid,
        userid=userid,
        request_type=RequestType.DOS.value,
        prompt="hello world",
    )

    jobdetail = Job.from_jobs(jobs, None)
    assert jobdetail.sessionid == sessionid
    assert jobdetail.id == id


def test_end_to_end_backgroundjob() -> None:
    sessionid = uuid4()
    userid = uuid4()
    id = uuid4()

    bgjob = BackgroundJob(
        id=id,
        client_ip="127.0.0.1",
        userid=userid,
        status=JobStatus.Created.value,
        prompt="hello world",
        response="nothing to say",
        request_type=RequestType.DOS.value,
        runtime=0.0,
        job_metadata="metadata",
        sessionid=sessionid,
    )
    jobs = Jobs.from_backgroundjob(bgjob)
    assert jobs.sessionid.hex == sessionid.hex
