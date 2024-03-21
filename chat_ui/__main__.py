""" cli runner for chat-ui """

import click


@click.command()
@click.option("--host", default="127.0.0.1")
@click.option("--reload", is_flag=True, help="Auto-reload for testing", default=False)
@click.option(
    "--jsonlogs", is_flag=True, help="Output logs in JSON format", default=True
)
def main(reload: bool = False, host: str = "127.0.0.1", jsonlogs: bool = True) -> None:
    """main function"""

    # logging.basicConfig(handlers=[logs.InterceptHandler()], level=0, force=True)

    import uvicorn

    if reload:
        workers = 1
    else:
        workers = 4

    options = {
        "reload": False,
        "port": 9195,
        "host": host,
        "workers": workers,
        "forwarded_allow_ips": "*",
        "timeout_keep_alive": 5,
    }

    if reload:
        options["reload"] = True
        options["reload_dirs"] = ["chat_ui"]

    uvicorn.run("chat_ui:app", **options)  # type: ignore


if __name__ == "__main__":
    main()
