"""Discover and validate Sofascore team IDs for WC 2026 registry teams."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")

from core.sofascore_team_discovery import (  # noqa: E402
    discover_sofascore_team_ids,
    seed_wc2026_discovery_rows,
    validated_name_id_map,
)
from data.sofascore import SofascoreClient  # noqa: E402

REPORTS = BACKEND / "reports"
VALIDATED_JSON = BACKEND / "data" / "sofascore_validated_team_ids.json"


def _print_table(rows) -> None:
    print(
        f"{'Registry key':<28} {'English':<14} {'ID':>6} {'Conf':<9} "
        f"{'Code':<6} {'Query':<22} Reason"
    )
    print("-" * 110)
    for row in rows:
        tid = row.sofascore_team_id if row.sofascore_team_id is not None else "-"
        reg_short = row.registry_key.split(" (")[0]
        print(
            f"{reg_short:<28} {row.english_name:<14} {str(tid):>6} {row.confidence:<9} "
            f"{(row.selected_name_code or '-'):<6} {row.search_query:<22} "
            f"{row.rejection_reason or ''}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover Sofascore NT team IDs")
    parser.add_argument("--sleep", type=float, default=0.75)
    parser.add_argument(
        "--seed-wc2026",
        action="store_true",
        help="Use curated WC 2026 tournament IDs (no live API; for validation/seed)",
    )
    parser.add_argument("--save-validated", action="store_true", help="Write validated JSON map")
    parser.add_argument("--csv", type=str, default="", help="Optional CSV output path")
    args = parser.parse_args()

    if args.seed_wc2026:
        print("Sofascore discovery: seed mode (WC 2026 curated IDs, no live API)")
        rows, id_map = seed_wc2026_discovery_rows()
    else:
        os.environ.setdefault("SOFASCORE_ENABLED", "true")
        client = SofascoreClient()
        if not client.key_present:
            print("SOFASCORE_RAPIDAPI_KEY is not set in backend/.env")
            print("Use --seed-wc2026 to validate curated WC 2026 IDs without live API.")
            return 1

        print(f"Sofascore discovery: enabled={client.enabled} key_present=True")
        rows, id_map = discover_sofascore_team_ids(client, sleep_seconds=args.sleep)
    _print_table(rows)

    exact = sum(1 for r in rows if r.confidence == "exact")
    likely = sum(1 for r in rows if r.confidence == "likely")
    ambiguous = sum(1 for r in rows if r.confidence == "ambiguous")
    missing = sum(1 for r in rows if r.confidence == "missing")
    print()
    print(
        f"Summary: exact={exact} likely={likely} ambiguous={ambiguous} "
        f"missing={missing} validated_map={len(id_map)}"
    )

    if args.save_validated:
        payload = {
            "by_registry_key": id_map,
            "by_english_name": validated_name_id_map(rows),
        }
        VALIDATED_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote validated mappings to {VALIDATED_JSON}")

    csv_path = Path(args.csv) if args.csv else REPORTS / "sofascore_team_id_discovery.csv"
    if args.csv or args.save_validated:
        REPORTS.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].to_dict().keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow(row.to_dict())
        print(f"Wrote {csv_path}")

    return 0 if not missing and not ambiguous else 2


if __name__ == "__main__":
    raise SystemExit(main())
