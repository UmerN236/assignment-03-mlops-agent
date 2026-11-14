"""Local conversational endpoint; separate from the model inference application."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from mlops_agent.agent import Agent, ChatRequest, ConversationResult, configure_logging
from mlops_agent.config import load_settings


def create_app(agent=None):
    app = FastAPI(title="Assignment MLOps conversational agent")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # FastAPI's default validation detail echoes input. Never export submitted secrets.
        return JSONResponse(status_code=422, content={"error": "Invalid conversational request"})

    @app.get("/livez")
    def livez():
        return {"status": "alive"}

    @app.post("/chat", response_model=ConversationResult)
    def chat(request: ChatRequest):
        result = (agent or Agent(load_settings())).run(request)
        return JSONResponse(
            status_code=200 if result.status == "complete" else 503,
            content=result.model_dump(mode="json"),
        )

    return app


configure_logging()
app = create_app()
