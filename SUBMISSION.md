# Assignment 03 submission

Submit this **public GitHub repository URL** to the course submission portal:

[github.com/UmerN236/assignment-03-mlops-agent](https://github.com/UmerN236/assignment-03-mlops-agent)

Use the **`v1.0.1` submission tag** to identify the final reviewed snapshot.
The assignment asks for one repository containing source, infrastructure, tests
and documentation. The report and evidence below are included in this repository;
the brief does not require a separate ZIP, video or PDF report upload.

## Included deliverables

| Deliverable | Location |
| --- | --- |
| Installation, configuration, service startup and interaction | [README](README.md) |
| Complete system architecture | [Architecture](architecture.md) |
| Short technical report, limitations and improvements | [Technical report](docs/report.md) |
| Callable tool definitions and permissions | [Schema catalog](docs/tool-catalog.json), report and adapter runbooks |
| Five tested agent conversations with actual tool evidence | [Conversation index](docs/evidence/conversations/README.md) |
| Two failure investigations with causes, diagnosis, resolution and recovery | [Investigations](docs/failure-investigations.md) |
| DVC, MLflow, Airflow and Kubernetes exported observations | [Evidence directory](docs/evidence/) |
| Fresh-checkout instructions and actual reproduction evidence | [Procedure](docs/reproduction.md), [export](docs/evidence/reproduction-live.json) |
| Automated tests and pull-request CI | [Tests](tests/), [workflow](.github/workflows/ci.yaml) |
| Live evaluation and unexpected-failure preparation | [Defense guide](docs/defense.md) |
| Requirement-by-requirement evidence map | [Acceptance checklist](docs/requirements.md) |

## Final requirement audit

| Rubric area | Required evidence present |
| --- | --- |
| DVC, 15 marks | Seven tools, two genuine versions, Git/content lineage, differences/status and historical recovery |
| MLflow, 15 marks | Seven supported-client tools, real runs/experiments/metrics/artifacts, comparable selection and registry metadata |
| Airflow, 15 marks | Six authenticated Airflow 3 tools; real staged DAG, retries, quality gate, successful execution and failure diagnostics |
| Kubernetes, 15 marks | Five scoped read tools; two replicas, ClusterIP, probes, resources, ConfigMap, logs/events/version and denied mutations |
| Integrated agent, 15 marks | Native LLM tool calling, structured contracts, all-four-service assessment, factual references and no automatic retraining |
| Reliability and safety, 10 marks | 314 passing pytest cases, timeouts/failures/authorization tests, structured redacted logs and two recovered failures |
| GitHub and CI, 5 marks | Public repository, locked environment and passing pull-request lint/tests/offline evidence checks |
| Demonstration preparation, 10 marks | Five real conversations, operational exports, architecture explanation and unexpected-failure guide |

Run `make check`, `make verify-submission` and `make smoke` to repeat the
appropriate checks. The offline verifier validates five complete conversations,
45 exact factual references, terminal training success, read-only mandatory
assessment, readiness recovery and the independent fresh model reproduction.
Recorded exports describe observations at their timestamps, not a guarantee that
a local service remains running indefinitely.

## Still required from the student

Submit the repository URL through the portal and follow any additional portal
fields specified by the instructor. During evaluation, demonstrate dataset
provenance, model selection, pipeline execution, deployment diagnosis and
multi-tool reasoning. Be ready to explain the design and investigate an
unexpected failure using the defense guide. Prepared evidence does not replace
the student's live demonstration or oral defense.

Do not upload `.env`, kubeconfigs, service-account tokens, `.local/`, raw
authentication responses or Docker volumes. These remain excluded from Git.
Reviewers use their own provider key when reproducing live calls. Free-provider
availability/quota and the local single-node deployment limitations are described
in the report. Assessment marks remain the evaluator's decision.
