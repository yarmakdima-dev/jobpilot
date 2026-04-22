# Pipeline Runner

The S2 runner is a cron-friendly scheduler for the flat-file state store. It
scans `pipeline.json`, loads each role from `roles/{role_id}.json`, asks the
state machine for the next action, runs the registered handler, records the
transition in both `decisions.log` and the role's `state_history`, then writes
the updated pipeline table.

## Commands

Run one pass:

```bash
python -m orchestrator.runner --tick
```

Run continuously:

```bash
python -m orchestrator.runner --daemon
```

Override the daemon sleep interval:

```bash
python -m orchestrator.runner --daemon --sleep 60
```

## Config

The runner reads `orchestrator/config.yml` when present.

| Key | Default | Meaning |
| --- | --- | --- |
| `tick_seconds` | `300` | Seconds between daemon ticks |
| `daily_report_time` | `"07:00"` | Reserved for S3 daily report scheduling |

## State Machine

The current stub state path is:

| State | Action | Stub next state |
| --- | --- | --- |
| `sourced` | `A1.4` liveness check | `liveness_pending` |
| `f1_pending` | `F1` | `f1_passed` |
| `f1_passed` | `A0` | `researched` |
| `researched` | `F2` | `f2_passed` |
| `f2_passed` | `A2` + `A3` | `ready_to_submit` |
| `ready_to_submit` | `A4` | `applied` |
| `applied` | `A8` | `first_call` |
| `first_call` | `A5` | `interview_scheduled` |
| `interview_scheduled` | `A5` | `post_interview` |
| `post_interview` | `A6` | `closed` |

Terminal or waiting states return no action: `liveness_pending`, `f1_failed`,
`f2_failed`, `f2_blocked`, `closed`, and `error`.

## Liveness Pending Decision

S2 includes the `liveness_pending` state even though the Playwright liveness
module ships later in A1.4. The runner intentionally advances `sourced` roles to
`liveness_pending`, not directly to `f1_pending`, after the liveness-check stub.

Reasoning: auto-promoting unchecked postings to F1 would spend filter and
research budget on roles whose live status is unknown. Keeping them in
`liveness_pending` makes the missing A1.4 behavior visible and safe. When A1.4
lands, it should replace the stub with real outcomes:

| Liveness result | Next state |
| --- | --- |
| `alive` | `f1_pending` |
| `dead` | `closed` with reason `posting_dead` |
| `unknown` | human review queue / waiting state |

## Agent Registry

Handlers live in `orchestrator/agents.py`. S2 handlers are no-op stubs that
append an `agent_stub` event to `decisions.log`, for example:

```json
{"event":"agent_stub","agent_id":"F1","role_id":"acme-coo-20260421"}
```

Real agent code can replace a registry entry without changing the runner loop.

## Failure Behavior

Failures are role-local. If a role handler raises or returns a failed result,
the runner marks that role's pipeline row as `error`, records `last_error`, logs
a `state_transition` event to `decisions.log`, and continues with the next role.

## Concurrency

`--tick` takes a non-blocking exclusive lock beside `pipeline.json`. A second
runner exits that tick with `RunnerLockError` instead of waiting and risking two
simultaneous writers.

