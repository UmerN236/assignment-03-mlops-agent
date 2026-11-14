"""Small Airflow-side bridge to the isolated scientific Python environment."""

import json
import logging
import os
import subprocess
import time

OPERATIONS = {
    "validation",
    "preprocessing",
    "training",
    "evaluation",
    "quality_gate",
    "approve_candidate",
}


def run_stage(operation: str, request: dict) -> dict:
    if operation not in OPERATIONS:
        raise ValueError("Unapproved workflow stage")
    environment = {
        "PATH": os.defpath,
        "PYTHONPATH": "/opt/project/src",
        "MLFLOW_TRACKING_URI": "http://mlflow:5000",
        "MLFLOW_HTTP_REQUEST_TIMEOUT": "20",
        "MLFLOW_HTTP_REQUEST_MAX_RETRIES": "0",
        "MLFLOW_ENABLE_ASYNC_LOGGING": "false",
        "MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT": "true",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "NETRC": os.devnull,
        "XDG_CACHE_HOME": "/opt/airflow/training-cache",
        "MPLCONFIGDIR": "/opt/airflow/training-cache/matplotlib",
    }
    started, status = time.monotonic(), "error"
    try:
        result = subprocess.run(
            ["/opt/training/bin/python", "-m", "mlops_agent.pipeline", operation],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            env=environment,
            timeout=240,
            check=False,
            shell=False,
        )
        response = json.loads(result.stdout)
        if result.returncode or response.get("status") != "ok":
            raise RuntimeError("Pipeline stage failed: " + operation)
        status = "ok"
        return {"completed_stage": operation}
    except subprocess.TimeoutExpired:
        raise RuntimeError("Pipeline stage timed out: " + operation) from None
    except (OSError, ValueError, AttributeError):
        raise RuntimeError("Pipeline worker unavailable or invalid: " + operation) from None
    finally:
        logging.info(
            json.dumps(
                {
                    "tool": "airflow_" + operation,
                    "status": status,
                    "duration_ms": (time.monotonic() - started) * 1000,
                    "request_id": request["workflow_run_id"],
                }
            )
        )
