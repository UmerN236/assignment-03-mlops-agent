"""Prediction application only; conversational operations belong to another API."""

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from mlops_agent.model_bundle import CLASSES, FEATURES, load_bundle, predict, read_manifest

logger = logging.getLogger("mlops_agent.inference")
logging.basicConfig(level=logging.INFO, format="%(message)s")
Measurement = Annotated[float, Field(strict=True, gt=0, lt=20, allow_inf_nan=False)]


class IrisFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sepal_length: Measurement
    sepal_width: Measurement
    petal_length: Measurement
    petal_width: Measurement


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instances: list[IrisFeatures] = Field(min_length=1, max_length=100)


def create_app(bundle_path: Path | None = None, app_version: str | None = None) -> FastAPI:
    directory = bundle_path or Path(os.getenv("MODEL_BUNDLE_PATH") or "artifacts/inference")
    if app_version is None:
        version_file = Path("/app/app-version")
        app_version = version_file.read_text().strip() if version_file.is_file() else "development"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        started = time.monotonic()
        app.state.model = None
        app.state.manifest = None
        app.state.failure = "model_bundle_invalid"
        try:
            app.state.manifest = read_manifest(directory)
            app.state.model = load_bundle(directory, app.state.manifest)
            app.state.failure = None
        except Exception:
            # Do not leak paths, deserialization errors, or arbitrary metadata.
            pass
        logger.info(
            json.dumps(
                {
                    "tool_name": "inference.load_model",
                    "status": "ok" if app.state.model is not None else "unavailable",
                    "duration_ms": round((time.monotonic() - started) * 1000, 3),
                    "request_id": str(uuid4()),
                }
            )
        )
        yield
        app.state.model = None

    application = FastAPI(title="Assignment Iris Inference", version="1.0.0", lifespan=lifespan)

    @application.middleware("http")
    async def trace(request: Request, call_next):
        request_id, started = str(uuid4()), time.monotonic()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        logger.info(
            json.dumps(
                {
                    "tool_name": f"inference.{route.name if route else 'unknown'}",
                    "status": "ok" if response.status_code < 400 else "error",
                    "http_status": response.status_code,
                    "duration_ms": round((time.monotonic() - started) * 1000, 3),
                    "request_id": request_id,
                }
            )
        )
        return response

    @application.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "detail": "Invalid inference input",
                "errors": [
                    {
                        # Locations can contain arbitrary caller-supplied keys.
                        "location": [
                            part
                            if type(part) is int or part in {"body", "instances", *FEATURES}
                            else "unknown_field"
                            for part in e["loc"]
                        ],
                        "type": e["type"],
                    }
                    for e in exc.errors()
                ],
                "request_id": request.state.request_id,
            },
        )

    @application.get("/livez")
    def liveness():
        return {"status": "alive"}

    @application.get("/readyz")
    def readiness():
        if application.state.model is None:
            raise HTTPException(503, "model_unavailable")
        return {"status": "ready", "model_run_id": application.state.manifest.selection.run_id}

    @application.get("/version")
    def version():
        manifest = application.state.manifest
        return {
            "application": "assignment-iris-inference",
            "app_version": app_version,
            "model_ready": application.state.model is not None,
            "model": manifest.selection.model_dump(mode="json") if manifest else None,
            "feature_order": FEATURES,
            "feature_units": "centimeters",
            "classes": CLASSES,
        }

    @application.post("/predict")
    def prediction(body: PredictionRequest):
        if application.state.model is None:
            raise HTTPException(503, "model_unavailable")
        rows = [[getattr(row, name) for name in FEATURES] for row in body.instances]
        try:
            labels, probabilities = predict(application.state.model, rows)
        except Exception:
            application.state.model = None
            application.state.failure = "model_prediction_failed"
            raise HTTPException(503, "model_prediction_failed") from None
        return {
            "predictions": [
                {"class_id": label, "class_name": CLASSES[label], "probabilities": scores}
                for label, scores in zip(labels, probabilities, strict=True)
            ],
            "model_run_id": application.state.manifest.selection.run_id,
            "app_version": app_version,
        }

    return application


app = create_app()
