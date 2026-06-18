#!/usr/bin/env python3
"""Explain baseline vs active candidate shift for a matchup (Phase 3D)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.activation_shift_explainer import (
    explain_activation_shift,
    format_explanation_markdown,
    human_explanation_summary,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Explain activation shift for a matchup.")
    parser.add_argument("--home", default="Germany")
    parser.add_argument("--away", default="Haiti")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    explanation = explain_activation_shift(args.home, args.away)
    print(human_explanation_summary(explanation))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(explanation, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(format_explanation_markdown(explanation), encoding="utf-8")
        print(f"Wrote {args.markdown}")


if __name__ == "__main__":
    main()
