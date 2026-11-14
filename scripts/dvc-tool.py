"""Call one registered DVC tool or print all input/output schemas."""

import json
import sys
from pathlib import Path

from mlops_agent.config import load_settings
from mlops_agent.dvc_tools import DvcTools
from mlops_agent.mlflow_tools import MlflowTools

settings = load_settings()
mlflow = MlflowTools(settings.mlflow_tracking_uri, settings.tool_timeout_seconds)
tools = DvcTools(Path(__file__).resolve().parents[1], run_lookup=mlflow.run_params).registry
if sys.argv[1:] == ["--schemas"]:
    print(json.dumps([tool.schema() for tool in tools.tools.values()], indent=2))
elif len(sys.argv) == 3:
    try:
        args = json.loads(sys.argv[2])
    except json.JSONDecodeError:
        raise SystemExit("Arguments must be a JSON object") from None
    if not isinstance(args, dict):
        raise SystemExit("Arguments must be a JSON object")
    result = tools.call(sys.argv[1], args)
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status == "ok" else 1)
else:
    raise SystemExit("Usage: dvc-tool.py --schemas | TOOL_NAME '{JSON_ARGUMENTS}'")
