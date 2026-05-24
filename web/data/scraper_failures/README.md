# Scraper failure snapshots

Per-failure diagnostic dumps written by [automation/scraper_failures.py](../../../automation/scraper_failures.py) when a source raises during the nightly run **or** silently returns zero records. One JSON file per failure:

```
<source>_<ts>_<failure_id>.json
```

Each file carries the exception class + repr, the request URL/method/headers (with `Authorization` / `Cookie` redacted), and the response status + headers + first 4KB of body — enough for the watchdog or the Phase-4 auto-repair agent to diagnose without re-running the scraper.

The matching `failure_id` is recorded on the row in [`web/data/source_health_history.jsonl`](../source_health_history.jsonl), so dashboards can deep-link from a red status entry to the snapshot.

Retention: the writer keeps the last 30 snapshots per source (≈ one month of nightlies) and prunes older files on each new write.

These files are checked in deliberately so the auto-repair agent's worktree has them available; Pulpo's response bodies are all from public real-estate sites — no secrets.
