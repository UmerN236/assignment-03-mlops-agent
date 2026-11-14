"""Call one MLflow read tool or inspect its schemas."""

import json
import sys

from mlops_agent.config import load_settings
from mlops_agent.mlflow_tools import MlflowTools

settings = load_settings()
registry = MlflowTools(settings.mlflow_tracking_uri, settings.tool_timeout_seconds).registry
if sys.argv[1:] == ["--schemas"]:
    print(json.dumps([tool.schema() for tool in registry.tools.values()], indent=2))
elif len(sys.argv) == 3:
    try:
        arguments = json.loads(sys.argv[2])
        if not isinstance(arguments, dict):
            raise ValueError
    except ValueError:
        raise SystemExit("Arguments must be a JSON object") from None
    result = registry.call(sys.argv[1], arguments)
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status == "ok" else 1)
else:
    raise SystemExit("Usage: mlflow-tool.py --schemas | TOOL_NAME '{JSON_ARGUMENTS}'")
