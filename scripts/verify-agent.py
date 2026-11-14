"""One real, read-only all-four-service conversation; no training or deployment."""

import argparse
import json
from pathlib import Path

from mlops_agent.agent import (
    ASSESSMENT_TOOLS,
    MANDATORY_PROMPT,
    Agent,
    ChatRequest,
    ConversationResult,
    configure_logging,
)
from mlops_agent.config import load_settings

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, default=Path(".local/agent-verification.json"))
parser.add_argument(
    "--from-json",
    type=Path,
    help="Validate a captured actual conversation instead of spending more free quota",
)
args = parser.parse_args()
configure_logging()
if args.from_json:
    result = ConversationResult.model_validate_json(args.from_json.read_text())
else:
    result = Agent(load_settings()).run(ChatRequest(message=MANDATORY_PROMPT, mode="assessment"))
names = {c["result"]["tool"] for c in result.tool_calls}
checks = {
    "conversation_complete": result.status == "complete",
    "all_four_services": ASSESSMENT_TOOLS <= names,
    "selected_lineage_verified": result.correlation["selected_lineage_verified"],
    "all_tool_responses_ok": all(c["result"]["status"] == "ok" for c in result.tool_calls),
    "one_request_id": all(
        c["result"]["request_id"] == result.request_id for c in result.tool_calls
    ),
    "no_trigger": "airflow_trigger_training" not in names,
    "only_assessment_allowlist": names <= ASSESSMENT_TOOLS,
    "four_services_cited": {"dvc", "mlflow", "kubernetes", "airflow"}
    <= {f["tool"].split("_", 1)[0] for f in result.known_facts},
    "free_request_costs": bool(result.turns) and all(t["cost"] == 0 for t in result.turns),
}
payload = {
    "prompt": MANDATORY_PROMPT,
    "checks": checks,
    "conversation": result.model_dump(mode="json"),
}
args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n")
print(json.dumps({"status": result.status, "request_id": result.request_id, "checks": checks}))
raise SystemExit(0 if all(checks.values()) else 1)
