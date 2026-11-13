"""Match club names across sources.

The fixtures source provides the reference names. A name from another source matches if
it is the same after normalising, or if data/club_aliases.yaml maps it. Anything else is
reported as unmatched; no match is ever guessed.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml

from uclfa.ingest.run import DATA_DIR, latest_snapshot

NOISE = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "sk", "fk", "bk", "club", "de", "the"}


def normalise(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    words = [w for w in re.split(r"[^a-z0-9]+", text) if w and w not in NOISE]
    return " ".join(words)


def load_aliases(data_dir: Path = DATA_DIR) -> dict[str, str]:
    """Alias (normalised) -> reference club name."""
    path = data_dir / "club_aliases.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for reference, aliases in (data.get("clubs") or {}).items():
        for alias in aliases or []:
            out[normalise(str(alias))] = reference
    return out


def match_report(data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """Which club names in the Elo and odds snapshots match a club in the fixtures."""
    fixtures = latest_snapshot("fixtures", data_dir)
    if fixtures is None:
        return {"error": "No fixtures snapshot yet; run `uclfa fetch` first."}
    reference: dict[str, str] = {}
    for r in fixtures["records"]:
        for full, short in ((r["home"], r.get("home_short")), (r["away"], r.get("away_short"))):
            reference[normalise(full)] = full
            if short:
                reference[normalise(short)] = full
    aliases = load_aliases(data_dir)
    clubs = sorted(set(reference.values()))

    def resolve(name: str) -> str | None:
        key = normalise(name)
        return reference.get(key) or aliases.get(key)

    report: dict[str, Any] = {"reference_clubs": len(clubs)}
    elo = latest_snapshot("elo", data_dir)
    if elo is not None:
        rated = {resolve(r["club"]) for r in elo["records"]} - {None}
        report["elo"] = {
            "matched": len(rated),
            "fixture_clubs_without_rating": [c for c in clubs if c not in rated],
        }
    odds = latest_snapshot("odds", data_dir)
    if odds is not None:
        names = {n for r in odds["records"] for n in (r["home"], r["away"])}
        report["odds"] = {
            "matched": len([n for n in names if resolve(n)]),
            "unmatched_names": sorted(n for n in names if not resolve(n)),
        }
    return report
