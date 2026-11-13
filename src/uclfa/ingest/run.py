"""Run the fetchers: write dated snapshots, keep good data when a response is bad, and
produce the probe report."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from uclfa.ingest import http
from uclfa.ingest.sources import SOURCES, Parsed, Source
from uclfa.rules.model import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"

Fetcher = Callable[[Source, date, str | None], http.Response]


@dataclass
class Outcome:
    source: str
    title: str
    status: str  # ok | skipped | rejected | failed
    message: str
    records: int = 0
    snapshot: Path | None = None
    http_status: int | None = None
    quota: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    fields_seen: list[str] = field(default_factory=list)
    fields_missing: list[str] = field(default_factory=list)
    raw_sample: Any = None


def snapshot_dir(source_key: str, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "snapshots" / source_key


def latest_snapshot(source_key: str, data_dir: Path | None = None) -> dict[str, Any] | None:
    """The most recent accepted snapshot for a source, or None if there is none."""
    files = sorted(snapshot_dir(source_key, data_dir).glob("*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def fetch_source(
    source: Source,
    *,
    day: date | None = None,
    data_dir: Path = DATA_DIR,
    fetcher: Fetcher | None = None,
    env: dict[str, str] | None = None,
    now: datetime | None = None,
) -> Outcome:
    """Fetch one source. A bad response writes nothing, so the previous snapshot stays current."""
    from uclfa.ingest import sources as _sources

    env = os.environ if env is None else env
    now = now or datetime.now(UTC)
    day = day or now.date()
    fetcher = fetcher or _sources.fetch
    outcome = Outcome(source.key, source.title, "failed", "")

    key = env.get(source.secret_env) if source.secret_env else None
    if source.secret_env and not key:
        outcome.status = "skipped"
        outcome.message = f"No key in {source.secret_env}; nothing was requested."
        return outcome

    try:
        response = fetcher(source, day, key)
    except http.SourceError as exc:
        outcome.message = str(exc)
        return outcome
    outcome.http_status = response.status
    outcome.quota = {h: response.headers[h] for h in source.quota_headers if h in response.headers}

    parsed: Parsed = source.parse(response.text)
    outcome.records = len(parsed.records)
    outcome.problems = parsed.problems
    outcome.fields_seen = parsed.fields_seen
    outcome.fields_missing = parsed.fields_missing
    outcome.raw_sample = parsed.raw_sample

    if len(parsed.records) < source.minimum_records or (parsed.problems and not parsed.records):
        outcome.status = "rejected"
        outcome.message = (
            f"Response rejected: {len(parsed.records)} usable records, at least "
            f"{source.minimum_records} required. The previous snapshot stays current."
        )
        return outcome

    folder = snapshot_dir(source.key, data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day.isoformat()}.json"
    body = {
        "source": source.key,
        "title": source.title,
        "fetched_at": now.isoformat(),
        "url": http.redact(source.build_url(day, key)),
        "record_count": len(parsed.records),
        "problems": parsed.problems,
        "records": parsed.records,
    }
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    outcome.status = "ok"
    outcome.snapshot = path
    outcome.message = f"{len(parsed.records)} records saved to {path.relative_to(data_dir.parent)}."
    return outcome


def fetch_all(only: list[str] | None = None, **kwargs: Any) -> list[Outcome]:
    keys = only or list(SOURCES)
    unknown = [k for k in keys if k not in SOURCES]
    if unknown:
        raise ValueError(f"Unknown source(s): {', '.join(unknown)}. Known: {', '.join(SOURCES)}.")
    return [fetch_source(SOURCES[k], **kwargs) for k in keys]


def write_probe_report(outcomes: list[Outcome], data_dir: Path = DATA_DIR) -> Path:
    """Write data/probe/report.md and one raw sample per source."""
    folder = data_dir / "probe"
    folder.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Source probe report",
        "",
        f"Run at {datetime.now(UTC).isoformat(timespec='seconds')}.",
        "",
        "| Source | Result | HTTP | Records | Quota |",
        "|---|---|---|---|---|",
    ]
    for o in outcomes:
        quota = ", ".join(f"{k}={v}" for k, v in o.quota.items()) or "-"
        lines.append(f"| {o.title} | {o.status} | {o.http_status or '-'} | {o.records} | {quota} |")
    for o in outcomes:
        lines += ["", f"## {o.title}", "", f"- Result: **{o.status}**. {o.message}"]
        if o.fields_seen:
            lines.append(f"- Fields returned: {', '.join(o.fields_seen)}")
        missing = ", ".join(o.fields_missing) if o.fields_missing else "none"
        lines.append(f"- Expected fields missing: {missing}")
        if o.problems:
            lines.append(f"- Problems ({len(o.problems)}), first five:")
            lines += [f"  - {p}" for p in o.problems[:5]]
        if o.raw_sample is not None:
            sample = folder / f"{o.source}-sample.json"
            sample.write_text(
                json.dumps(o.raw_sample, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            lines.append(f"- Raw sample: `data/probe/{sample.name}`")
    path = folder / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
