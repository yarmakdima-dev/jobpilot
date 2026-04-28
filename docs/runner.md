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

The current state path is:

| State | Action | Next state |
| --- | --- | --- |
| `sourced` | `A1.4` liveness queue step | `liveness_pending` |
| `liveness_pending` | Playwright liveness check | `f1_pending` or `dead` |
| `f1_pending` | `F1` JD pre-screen | `f1_passed`, `f1_failed`, or `f1_near_miss` |
| `f1_passed` | Research init | `researching` |
| `researching` | `A0` company research | `researched` or `research_failed` |
| `researched` | `F2` deep rubric evaluation | `f2_passed`, `f2_failed`, or `f2_blocked` |
| `f2_passed` | `A2` + `A3` | `ready_to_submit` |
| `ready_to_submit` | `A4` | `applied` |
| `applied` | `A8` | `first_call` |
| `first_call` | `A5` | `interview_scheduled` |
| `interview_scheduled` | `A5` | `post_interview` |
| `post_interview` | `A6` | `closed` |

Terminal or waiting states return no action: `dead`, `f1_failed`, `f2_failed`,
`f2_blocked`, `research_failed`, `closed`, and `error`.

`f1_near_miss` is intentionally a hold state today because it has no automatic
transition. It should be reviewed from the daily report and moved by a human
override once the ambiguity is resolved.

## Liveness Check

The runner advances `sourced` roles to `liveness_pending`, then runs the
Playwright liveness module on the following tick. This keeps unchecked postings
out of F1 and A0 until the posting page is confirmed live.

| Liveness result | Next state |
| --- | --- |
| live posting | `f1_pending` |
| dead posting, missing JD, timeout, or inaccessible page | `dead` |

## Agent Registry

Handlers live in `orchestrator/agents.py` and `orchestrator/state_machine.py`.
Some late-stage handlers are still no-op stubs that append an `agent_stub` event
to `decisions.log`, for example:

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
