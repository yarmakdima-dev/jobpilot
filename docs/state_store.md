# State Store

JobPilot starts with a flat-file state store. Runtime data stays in the User Layer,
while schemas and orchestration code stay in the System Layer.

## Files

| Path | Purpose |
| --- | --- |
| `roles/{role_id}.json` | One role record, validated by `schemas/role.schema.json` |
| `companies/{domain}.json` | One company profile, aligned to `company_profile_schema.json` |
| `pipeline.json` | Flat active pipeline table, validated by `schemas/pipeline.schema.json` |
| `decisions.log` | Append-only newline-delimited JSON audit log |

## API

```python
from orchestrator.store import (
    append_decision,
    read_company,
    read_pipeline,
    read_role,
    write_company,
    write_pipeline,
    write_role,
)
```

### Roles

`read_role(role_id) -> dict` reads `roles/{role_id}.json`.

`write_role(role_id, data, writer_id) -> None` validates the role schema, checks
the writer's lane, and writes atomically through a temporary file plus rename.
Role write scope is narrower than path access for these actors:

| Writer | Scope |
| --- | --- |
| `A1` | Create new role files only |
| `F1` | Update `filter_status.f1` only |
| `F2` | Update `filter_status.f2` and top-level `gate_needs_judgment_call` only |
| `A6` | Update `debrief_ref` only |

The `system` writer is reserved for orchestrator-owned state movement: role
`pipeline_state`, role `state_history`, `pipeline.json`, and audit entries in
`decisions.log`. Agents should not use it directly.

### Companies

`read_company(domain) -> dict` reads `companies/{domain}.json`.

`write_company(domain, data, writer_id) -> None` checks the writer lane and
validates against `company_profile_schema.json`. The current company profile
schema is the canonical system document for company shape.

### Pipeline

`read_pipeline() -> list[dict]` reads and validates `pipeline.json`. Missing
pipeline state is treated as an empty list.

`write_pipeline(data, writer_id) -> None` validates the pipeline schema and
writes atomically. The system runner should use `writer_id="system"`.

### Decisions

`append_decision(entry) -> None` appends one JSON object per line to
`decisions.log`. If `at` is omitted, the store adds the current UTC timestamp.

## Lane Violations

Lane checks live in `orchestrator.lanes`. A disallowed write raises
`LaneViolationError` and records a `lane_violation` event in `decisions.log`.

## Concurrency

Writes use a per-file `.lock` file and an exclusive `fcntl` lock. JSON writes are
atomic: data is written to a temporary file in the same directory, flushed, and
then moved into place with `os.replace`.
