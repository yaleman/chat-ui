import os
from chat_ui.config import Config


def test_config_admin_password() -> None:
    """testing the admin password functionality"""

    # in case you're running this test in an environment where the environment variable is set
    del os.environ["CHATUI_ADMIN_PASSWORD"]

    testconfig = Config()

    assert testconfig.admin_password is None

    os.environ["CHATUI_ADMIN_PASSWORD"] = "testpassword"

    testconfig = Config()

    assert testconfig.admin_password == "testpassword"

    del os.environ["CHATUI_ADMIN_PASSWORD"]

    testconfig = Config()

    assert testconfig.admin_password is None
