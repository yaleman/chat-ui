""" cli runner for chat-ui """

import click


@click.command()
@click.option("--reload", is_flag=True, help="Auto-reload for testing")
def main(reload: bool = False) -> None:
    """main function"""
    import uvicorn

    uvicorn.run("chat_ui:app", reload=reload, port=9195)


if __name__ == "__main__":
    main()
