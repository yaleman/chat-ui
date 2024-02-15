from uuid import uuid4
from chat_ui import AppState
from chat_ui.models import NewJob


def test_hidden_job() -> None:
    """test hiding a job"""
    state = AppState(db_path=":memory:")
    userid = str(uuid4())

    job = state.db.create_job(
        NewJob(userid=userid, prompt="test", request_type="plain")
    )

    assert job.status == "created"
    state.db.hide_job(userid=userid, id=job.id)
    hopefully_hidden = state.db.get_job(userid=userid, id=job.id)
    assert hopefully_hidden is not None
    assert hopefully_hidden.status == "hidden"
