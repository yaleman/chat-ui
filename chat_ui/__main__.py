""" cli runner for chat-ui """

import click


@click.command()
@click.option("--host", default="127.0.0.1")
@click.option("--reload", is_flag=True, help="Auto-reload for testing")
@click.option(
    "--jsonlogs", is_flag=True, help="Output logs in JSON format", default=True
)
def main(reload: bool = False, host: str = "127.0.0.1", jsonlogs: bool = True) -> None:
    """main function"""

    # logging.basicConfig(handlers=[logs.InterceptHandler()], level=0, force=True)

    import uvicorn

    uvicorn.run(
        "chat_ui:app",
        reload=reload,
        port=9195,
        host=host,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
