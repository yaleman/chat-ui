from datetime import UTC, datetime
from uuid import uuid4
import aiohttp
import pytest
from chat_ui.backgroundpoller import BackgroundPoller
from chat_ui.config import Config
from chat_ui.db import JobAnalysis
from chat_ui.models import AnalysisType


@pytest.mark.asyncio()
async def test_get_model() -> None:
    """tests getting the model"""

    async with aiohttp.ClientSession() as session:
        url = Config().backend_url
        if url is None:
            pytest.skip("No backend url configured!")
        url = "/".join(url.split("/")[:-1])
        url = f"{url}/docs"
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    pytest.skip("Backend is wrong")
        except Exception as error:
            pytest.skip(f"Failed to connect to backend for tests, skipping! {error=}")

    bgp = BackgroundPoller(engine=None)  # type: ignore

    model_name = await bgp.get_model_name()

    print(model_name)


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
