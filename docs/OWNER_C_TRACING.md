# Owner C tracing

The tracing layer answers three questions: where a workflow spent time, why an
overlay was approved/repaired/replaced, and how many model tokens that run used.
It changes neither the football contracts nor the existing model deadlines.

## Enable Azure export

Owner A supplies the team's Application Insights connection string privately.
Save it only in the ignored `.env` as `APPLICATIONINSIGHTS_CONNECTION_STRING` and
restart the API using the local Foundry settings in [OWNER_C.md](OWNER_C.md).
Keep the value out of chat, Git, screenshots and exported patches.

Configuration runs once at plugin setup. With no connection string, no Azure
exporter is imported or created. `AGENT_MODE=stub` always skips automatic Azure
configuration; tests can explicitly inject a local tracer. Configuration failures
leave the match running and log only the exception type. Fix configuration and
restart to retry. Exporters remain process-wide, managed by the OTel SDK.
`OTEL_SERVICE_NAME` is honored; its default is `everyfan-owner-c`.

The current student subscription was checked with a read-only resource listing:
it has no Application Insights component. Local tracing is verified; actual Azure
ingestion and the requested dashboard screenshot still require that resource and
connection string. Production managed identity, GitHub merge and deployment remain
team integration work; this phase did not create cloud resources or send messages.

## Trace shape and fields

`everyfan.workflow` covers accepted analytics callback work, including synchronous
Producer scheduling and the background queue. Direct callers can pass an explicit
`entry_point`; otherwise it is `direct`. The plugin uses `analytics_callback`.

Children are `agent.producer`, `agent.analyst`, `agent.writer`, `agent.verifier`,
`tool.<evidence method>`, `model.complete` and `overlay.publish`. Evidence tool
spans cover the Analyst's five in-process evidence operations. Both Agent Framework
and plain async runtimes use the same instrumentation. Native framework spans are
enabled, when available, only during Azure configuration.

Attributes use the `everyfan.` prefix: `match_id`, `moment_id`, `persona`, `lang`,
`model`, `tokens`, `charged_tokens`, `usage_unknown`, `verdict`, `reason_code`,
`attempts`, `outcome`, `entry_point`, `approved`, `fallback`, `count`, `tool_name`,
`confidence` and `error_type`. Not every field applies to every span.

`tokens` sums reported usage for that span's subtree. `charged_tokens` also
includes conservative charges when transport/cancellation leaves usage unknown.
These are isolated with async context, so concurrent workflows do not borrow each
other's totals. Stage/tool duration comes from span timestamps; very short
synchronous work may have zero duration at the local clock's resolution.

Verdict/repair/fallback events carry metadata and reason codes. A timeout or error
inside the Analyst is marked as fallback with its reason, even if subsequent
writers produce approved overlays. Stale replay runs are marked `stale` and cannot
publish. Cancelled work closes spans and preserves existing budget settlement.

Only allowlisted scalar metadata is added to manual spans/events. Prompt text,
draft text, tool arguments/results, exception messages and credentials are not
captured. Native sensitive data and message events are explicitly disabled.
Automatic HTTP/database instrumentation is disabled for this integration. Logs
and metrics exporters default to `none` unless the operator explicitly sets them;
live metrics/performance counters and exporter disk retry storage are disabled.

## Inspect locally and in Azure

Run this entirely offline, with the project Python 3.12 environment:

```powershell
.\.venv\py312\Scripts\python.exe -m backend.agents.trace_demo --out .venv/handoff/owner-c-phase6-traces.json
```

The JSON contains two traces (approval and forced repair/fallback), their spans,
and final overlays for correlation. It uses real local evidence, stub generation,
and a local exporter. It does not initialize an Azure exporter or call Foundry.

For Azure, copy an overlay's `trace_id` into Application Insights Logs:

```kusto
union requests, dependencies
| where operation_Id == "<overlay.trace_id>"
| project timestamp, name, duration, operation_ParentId, customDimensions
| order by timestamp asc
```

Find the workflow and its children, then inspect `everyfan.reason_code`, verdict
and usage attributes. Capture the trace view after successful ingestion for the
README/video; the local JSON is not a substitute for that Azure screenshot.

Official interfaces: [Azure Monitor configuration](https://learn.microsoft.com/en-us/python/api/azure-monitor-opentelemetry/azure.monitor.opentelemetry?view=azure-python)
and [Agent Framework observability](https://learn.microsoft.com/en-us/agent-framework/agents/observability?pivots=programming-language-python).
Dependencies are pinned to `azure-monitor-opentelemetry==1.8.11` and
`opentelemetry-sdk==1.45.1`; the existing Agent Framework 1.23 instrumentation
signature was inspected before use.

Validation: **430 tests passed**, including 15 tracing tests; pyflakes and
`pip check` passed. Tests use only local/fake exporters and never call Azure or
a real model. A deliberately inverted attribute allowlist was caught by its
regression test and restored before the final checks.
