"""Offline acceptance check of captured real conversations and submission artifacts."""

import json
from pathlib import Path

from mlops_agent.agent import ASSESSMENT_TOOLS, ConversationResult, resolve_pointer

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "docs/evidence/conversations"
    results = []
    for path in sorted(directory.glob("0[1-5]-*.json")):
        payload = json.loads(path.read_text())
        result = ConversationResult.model_validate(payload["conversation"])
        assert result.status == "complete", f"Incomplete scenario: {path.name}"
        assert result.provider.get("free_tier_verified") is True
        assert result.turns and all(t["cost"] == 0 for t in result.turns)
        assert result.tool_calls and result.known_facts
        for call in result.tool_calls:
            assert call["result"]["request_id"] == result.request_id
            assert call["result"]["status"] == "ok"
        for fact in result.known_facts:
            observed = result.tool_calls[fact["result_index"]]["result"]
            assert fact["tool"] == observed["tool"]
            assert fact["value"] == resolve_pointer(observed["evidence"], fact["pointer"])
        results.append((path.name, result))
    assert len(results) == 5, "Five distinct complete conversations are required"
    pipeline = results[2][1]
    statuses = [
        c["result"]["evidence"]
        for c in pipeline.tool_calls
        if c["result"]["tool"] == "airflow_get_run"
    ]
    assert statuses[-1]["terminal"] and statuses[-1]["run"]["state"] == "success"
    mandatory = results[4][1]
    names = {c["result"]["tool"] for c in mandatory.tool_calls}
    assert ASSESSMENT_TOOLS <= names and "airflow_trigger_training" not in names
    assert mandatory.correlation["selected_lineage_verified"] is True
    assert mandatory.retraining["initiated_by_assessment"] is False
    failed = json.loads((ROOT / "docs/evidence/readiness-failure-live.json").read_text())
    assert failed["recovered"]
    unhealthy = next(r["evidence"] for r in failed["during"] if r["tool"] == "kubernetes_workloads")
    assert unhealthy["deployments"][0]["ready_replicas"] == 0
    recovered = next(r["evidence"] for r in failed["after"] if r["tool"] == "kubernetes_workloads")
    assert recovered["deployments"][0]["ready_replicas"] == 2
    assert failed["agent_diagnosis"]["known_facts"]
    reproduction = json.loads((ROOT / "docs/evidence/reproduction-live.json").read_text())
    assert (
        reproduction["fresh_tracking_database"] and not reproduction["original_tracking_state_used"]
    )
    assert reproduction["training_runs"] >= 5 and reproduction["checks"]
    assert reproduction["prediction"]["model_run_id"] == reproduction["candidate_run_id"]
    assert "- [ ]" not in (ROOT / "docs/requirements.md").read_text()
    for name in (
        "report.md",
        "defense.md",
        "failure-investigations.md",
        "evidence/conversations/README.md",
    ):
        assert (ROOT / "docs" / name).is_file(), name
    print(
        json.dumps(
            {
                "status": "passed",
                "complete_conversations": len(results),
                "fact_references_verified": sum(len(r.known_facts) for _, r in results),
                "live_workflow_success": True,
                "mandatory_read_only": True,
                "readiness_recovered": True,
                "fresh_model_reproduction": True,
            }
        )
    )


if __name__ == "__main__":
    main()
