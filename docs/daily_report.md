# Daily Report

S3 adds a markdown morning digest for the flat-file pipeline state. It is designed
to be read directly from `reports/` in a terminal, text editor, or markdown
viewer.

## Generate a Report

Run:

```bash
python -m orchestrator.report --date 2026-04-22 --out reports/daily_2026-04-22.md
```

If `--out` is omitted, the generator writes to:

```text
reports/daily_YYYY-MM-DD.md
```

The public Python API is:

```python
from orchestrator.report import generate_report, write_daily_report

markdown = generate_report("2026-04-22")
path = write_daily_report("2026-04-22")
```

## Sections

Every report contains the same sections. Empty sections render as `—` so the
shape of the report stays stable.

- `Pipeline snapshot`: counts active pipeline rows by major state and flags
  roles that have been in a non-terminal state for more than seven days.
- `Needs your attention`: roles awaiting approval in `ready_to_submit`, roles
  with `filter_status.f2.stance = "blocked"`, roles in `error`, and files in
  `inbox_events/`.
- `Funnel metrics (7-day)`: conversion rates from role `state_history` and
  source discovery timestamps over the last seven days.
- `Near-misses`: roles with `filter_status.f1.status = "near_miss"` checked in
  the last 24 hours.
- `Overrides logged`: `decisions.log` events whose `event` contains
  `override`, limited to the last 24 hours.
- `Errors`: roles or pipeline rows in `error`, with `last_error` preferred when
  present.

## Scheduled Reports

`python -m orchestrator.runner --daemon` checks report generation after each
tick. The daemon writes one report per local calendar day after the configured
time has passed.

Configure the schedule in `orchestrator/config.yml`:

```yaml
tick_seconds: 300
daily_report_time: "07:00"
```

The time is interpreted in the machine's local timezone.

## Customizing

The markdown layout lives in `templates/daily_report.md.j2`. Keep section names
stable so downstream readers and tests can rely on the report shape. The data
assembly logic lives in `orchestrator/report.py`; add new fields there before
referencing them in the template.
