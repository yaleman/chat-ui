""" cli runner for chat-ui """

import click


@click.command()
@click.option("--host", default="127.0.0.1")
@click.option("--reload", is_flag=True, help="Auto-reload for testing")
def main(reload: bool = False, host: str = "127.0.0.1") -> None:
    """main function"""
    import uvicorn

    uvicorn.run("chat_ui:app", reload=reload, port=9195, host=host)


if __name__ == "__main__":
    main()
