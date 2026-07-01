"""NR3+FCC served xG decomposition diagnostics (display-only; no math changes)."""

from __future__ import annotations

from typing import Any


def _round_pair(home_xg: float, away_xg: float) -> tuple[float, float]:
    return round(float(home_xg), 2), round(float(away_xg), 2)


class Nr3XgDecompositionBuilder:
    """Capture before/after xG snapshots along the NR3 served path."""

    def __init__(
        self,
        *,
        home_team: str,
        away_team: str,
        active_model: str,
        legacy_home_xg: float,
        legacy_away_xg: float,
    ) -> None:
        self.home_team = home_team
        self.away_team = away_team
        self.active_model = active_model
        self.legacy_home_xg = float(legacy_home_xg)
        self.legacy_away_xg = float(legacy_away_xg)
        self.adjustments: list[dict[str, Any]] = []
        self._nr3_base_h = 0.0
        self._nr3_base_a = 0.0
        self._final_h = 0.0
        self._final_a = 0.0

    def set_nr3_base(self, home_xg: float, away_xg: float) -> None:
        self._nr3_base_h, self._nr3_base_a = _round_pair(home_xg, away_xg)

    def set_final(self, home_xg: float, away_xg: float) -> None:
        self._final_h, self._final_a = _round_pair(home_xg, away_xg)

    def record(
        self,
        *,
        name: str,
        display_name: str,
        before_home_xg: float,
        before_away_xg: float,
        after_home_xg: float,
        after_away_xg: float,
        status: str,
        explanation: str,
    ) -> None:
        bh, ba = _round_pair(before_home_xg, before_away_xg)
        ah, aa = _round_pair(after_home_xg, after_away_xg)
        self.adjustments.append(
            {
                "name": name,
                "display_name": display_name,
                "status": status,
                "before_home_xg": bh,
                "before_away_xg": ba,
                "after_home_xg": ah,
                "after_away_xg": aa,
                "delta_home_xg": round(ah - bh, 2),
                "delta_away_xg": round(aa - ba, 2),
                "explanation": explanation,
            }
        )

    def record_unchanged(
        self,
        *,
        name: str,
        display_name: str,
        status: str,
        explanation: str,
        home_xg: float,
        away_xg: float,
    ) -> None:
        self.record(
            name=name,
            display_name=display_name,
            before_home_xg=home_xg,
            before_away_xg=away_xg,
            after_home_xg=home_xg,
            after_away_xg=away_xg,
            status=status,
            explanation=explanation,
        )

    def build(self) -> dict[str, Any]:
        return {
            "active_model": self.active_model,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "nr3_base": {
                "home_xg": self._nr3_base_h,
                "away_xg": self._nr3_base_a,
                "label": "בסיס NR3 לפני התאמות",
            },
            "adjustments": list(self.adjustments),
            "final": {
                "home_xg": self._final_h,
                "away_xg": self._final_a,
                "label": "xG סופי לחיזוי",
            },
            "legacy_reference": {
                "home_xg": round(self.legacy_home_xg, 2),
                "away_xg": round(self.legacy_away_xg, 2),
                "label": "ייחוס מודל ישן / Maher",
                "note": "להשוואה בלבד — לא משמש כחישוב הפעיל",
            },
        }
