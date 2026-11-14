"""Manually triggered assignment workflow; no parse-time ML imports or I/O."""

from datetime import UTC, datetime, timedelta

from airflow.sdk import dag, task


@dag(
    dag_id="assignment_training",
    schedule=None,
    start_date=datetime(2026, 1, 1, tzinfo=UTC),
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(seconds=5),
        "execution_timeout": timedelta(minutes=5),
    },
    tags=["assignment", "candidate-only"],
    description="Validation → preprocessing → training → evaluation/MLflow → quality gate",
)
def training_pipeline():
    @task(multiple_outputs=False)
    def stage(operation: str, previous: dict | None = None) -> dict:
        from airflow.sdk import get_current_context

        from mlops_agent.workflow_task import run_stage

        context = get_current_context()
        request = dict(context["dag_run"].conf or {})
        request["workflow_run_id"] = context["run_id"]
        return run_stage(operation, request)

    validated = stage.override(task_id="validation")("validation")
    prepared = stage.override(task_id="preprocessing")("preprocessing", validated)
    trained = stage.override(task_id="training")("training", prepared)
    evaluated = stage.override(task_id="evaluation")("evaluation", trained)
    gated = stage.override(task_id="quality_gate")("quality_gate", evaluated)
    stage.override(task_id="approve_candidate")("approve_candidate", gated)


training_pipeline()
