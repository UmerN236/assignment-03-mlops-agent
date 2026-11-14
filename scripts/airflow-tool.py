"""Call one authenticated Airflow tool; explicit flag required for a trigger."""

import argparse
import json

from mlops_agent.airflow_tools import OPERATIONS, AirflowTools
from mlops_agent.config import load_settings

parser = argparse.ArgumentParser()
parser.add_argument("tool", choices=list(OPERATIONS))
parser.add_argument("--arguments", default="{}")
parser.add_argument("--schemas", action="store_true")
parser.add_argument("--allow-trigger", action="store_true", help="Explicitly authorize training")
args = parser.parse_args()
tools = AirflowTools(load_settings(), allow_trigger=args.allow_trigger)
if args.schemas:
    print(json.dumps([item.schema() for item in tools.registry.tools.values()], indent=2))
else:
    try:
        arguments = json.loads(args.arguments)
    except ValueError:
        parser.error("Arguments must be JSON")
    result = tools.registry.call("airflow_" + args.tool, arguments)
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.status == "ok" else 1)
