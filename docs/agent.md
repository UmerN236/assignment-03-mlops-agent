# Conversational agent

The selected provider is **OpenRouter**, using the user's configured free route.
The host uses its supported Chat Completions API with native function calls; it
never parses tool calls from generated prose. No framework or paid fallback is
needed. Gemini configuration remains accepted by the shared settings model for a
future adapter, but this agent explicitly returns unavailable for that provider.
Only the selected OpenRouter integration is implemented and live-validated.

Run `make setup`, start the existing assignment services/cluster using the
[README](../README.md), and configure the selected free account locally without
replacing an existing `.env`. `make config` reports presence booleans. Set
`LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, and either `OPENROUTER_MODEL` or
`LLM_MODEL` to the free route the user selected. Generic `LLM_MODEL` takes
precedence. No credential values belong in transcripts, Git, command arguments,
or requests to `/chat`.

```sh
make agent                  # mandatory read-only assessment
make verify-agent           # live assertions and local JSON export
make agent-api              # loopback http://127.0.0.1:8090
```

The API is for local use. Keep it bound to loopback. `/livez` reports process
liveness, not provider/service readiness. `/docs` shows request and response
schemas. `POST /chat` accepts a message and an optional mode; it returns actual
observations and an evidence-backed response with a request ID. Each call is a
self-contained conversational turn; the server does not retain client histories
or accept caller-supplied system messages or tool results.

```sh
curl -sS http://127.0.0.1:8090/chat \
  -H 'Content-Type: application/json' \
  -d '{"mode":"assessment","message":"Find the best recent model, identify the dataset version used to train it, check the deployment status, and explain whether retraining is necessary."}'

PYTHONPATH=src .venv/bin/python scripts/agent.py \
  'Read the inference deployment health and application version' --mode query
```

Query mode exposes 24 independently callable read tools: seven DVC, seven
MLflow, five Kubernetes and five Airflow. Each integration has at least three
independent tools. Assessment narrows the model-visible allowlist to seven tools:
experiments, selection, selected-run DVC resolution, workloads, health, Services,
and recent Airflow runs. The model chooses arguments and call order. Returned
experiment/run IDs drive dependent calls. Successful assessment requires actual
successful observations from all seven, matching selected-run lineage, and
factual citations from all four technologies. A missing service yields partial
results and explicit unknowns; it cannot become a fabricated healthy response.

The provider's schema describes each tool's strict Pydantic input. Service
results use the validated `ToolResult` envelope, and malformed/non-JSON evidence
is rejected. The model finishes through `submit_answer`, whose references are
resolved by the host into exact observed values using zero-based result indices
and JSON pointers. The model cannot insert its own metric or health value into a
known fact. Recommendations are constrained to review/investigation actions;
correlation compares actual selected, recorded and deployed identities.
Observations are timestamped independently rather than represented as an atomic
snapshot. Best F1 is not production readiness.

## Permissions and retraining

`query` and `assessment` have no training capability or Kubernetes mutations.
The exact mandatory prompt is always treated as assessment. Tool results and
model arguments cannot authorize writes. Kubernetes writes are unsupported,
including when a model claims confirmation. Restricted cluster credentials are
used, with no administrator fallback.

A separate explicit user training request can use `trigger_training` mode and
exact confirmation `trigger assignment_training`. Both must be provided by the
user at the host boundary; a model's own confirmation field is insufficient.
The host generates one stable run ID and allows at most one trigger attempt per
request, including when POST outcome is unknown. Query that ID before any later
retry. Normal adapter validation still restricts the DAG and canonical conf.
This authorization only triggers training; it does not approve registry
promotion or deployment.

```sh
PYTHONPATH=src .venv/bin/python scripts/agent.py \
  'Trigger the approved training workflow and report observed task states' \
  --mode trigger_training --confirmation 'trigger assignment_training'
```

The host deliberately reports retraining necessity as `not_established` without
an approved freshness/degradation policy. Historical controlled gate failures
are not production degradation. A candidate/deployment mismatch supports a
review recommendation, not automatic retraining. This version supports gathering
and citing evidence, then explicit user-requested training; automatic retraining
recommendations from supplied policies remain an extension.

## Bounds and failure behavior

- Actual key metadata must report a free-tier account. Current model catalog
  must contain the configured route. Explicit `:free` models additionally require
  tool support and zero input/output prices. The free router's documented feature
  filtering selects tool-compatible free models; actual selected IDs and reported
  costs are exported per turn.
- Requests require supported parameters and set zero maximum prompt, completion
  and request prices. No fallback model list or provider switch is configured.
  There is no purchase, billing enablement or retry to a paid model.
- Provider HTTP phase timeouts and a checked response deadline use
  `LLM_TIMEOUT_SECONDS` (default 60); output is capped at 2 MiB and 4096 tokens.
  The deadline is checked while consuming bytes, with HTTP read timeout bounding
  a stalled chunk. It is not a process-kill deadline for the complete conversation.
- `MAX_TOOL_ITERATIONS` (default 8, max 16), at most eight calls per model turn,
  and at most 32 executed service calls bound the loop. Service adapters retain
  their own bounded worker/subprocess deadlines.
- Missing credentials, 401/403, 402, 429, absent models, service/network errors,
  truncated calls, malformed JSON and provider timeout yield sanitized errors.
  No automatic LLM retry consumes additional free quota. Earlier observations
  remain available after a later failure.
- CLI exits nonzero for partial/unavailable results. HTTP returns 503 with the
  same evidence envelope, or sanitized 422 for invalid input. It never echoes
  validation inputs. It reports liveness separately from operational success.
- JSON tool logs on stderr contain tool, status, duration_ms and request_id.
  Validated arguments and operational results appear in the export. Invalid
  arguments are omitted; sanitized denials appear as policy_events. Provider
  reasoning/signatures are preserved only in memory for wire compatibility and
  are excluded from exports and logs.

## Official API references

Reviewed 14 November 2026. Live catalog/key checks and actual requests establish
availability; these links explain the protocol rather than proving a live run.

- [OpenRouter native tool calling](https://openrouter.ai/docs/guides/features/tool-calling)
- [Free router and feature filtering](https://openrouter.ai/docs/guides/routing/routers/free-router)
- [Provider parameter requirements and maximum prices](https://openrouter.ai/docs/guides/routing/provider-selection)
- [Model metadata API](https://openrouter.ai/docs/api/api-reference/models/get-models)
- [Limits and key metadata](https://openrouter.ai/docs/api/reference/limits)

See [live observations](evidence/agent.md) and the policy/failure tests in
`tests/test_agent.py` and `tests/test_provider.py`. Five complete conversations,
readiness failure/recovery and final report are separate remaining milestones.
