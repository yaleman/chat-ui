# chat-ui

A really simple FastAPI-based thing that provides a chatbot-looking UI.

## Configuration

All config options are prefixed with `CHATUI_`.

See the chatui.config.Config class for options, you can also set config options in `~/.config/chat-ui.json`.

## Request/Job flow

1. user sends a "job"
2. server takes the job and works on it in the background
3. user polls periodically for the response
4. winning
