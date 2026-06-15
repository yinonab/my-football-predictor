"""Hebrew explanations for prediction outputs — rule-based, not LLM."""

from __future__ import annotations


def _short_name(full_name: str) -> str:
    if "(" in full_name and ")" in full_name:
        return full_name.split("(")[1].rstrip(")").strip()
    return full_name


def explain_exact_score(
    score: str,
    probability: float,
    *,
    home_xg: float,
    away_xg: float,
    home_team: str,
    away_team: str,
    rank: int,
) -> str:
    """Generate a short Hebrew explanation for one exact-score line."""
    home_label = _short_name(home_team)
    away_label = _short_name(away_team)
    h, a = (int(x) for x in score.split("-"))
    total_goals = h + a
    xg_gap = home_xg - away_xg

    parts: list[str] = []

    if rank == 1:
        parts.append("התוצאה הסבירה ביותר לפי המודל.")
    elif rank <= 3:
        parts.append("בין התוצאות המובילות במטריצה.")
    elif probability >= 8:
        parts.append("תרחיש סביר עם מסה הסתברותית משמעותית.")
    else:
        parts.append("תרחיש אפשרי אך פחות שכיח.")

    if h == a:
        if h == 0:
            parts.append("תיקו ללא שערים — שתי ההגנות או xG נמוך משני הצדדים.")
        elif h == 1:
            parts.append(
                "תיקו 1-1 — מאוזן; מודל Dixon-Coles מחזק תוצאות תיקו בטווח נמוך."
            )
        else:
            parts.append(f"תיקו תוצאתי ({score}) — שתי התקפות מייצרות שערים.")
    elif h > a:
        margin = h - a
        if margin >= 2:
            parts.append(f"{home_label} שולטת עם יתרון התקפי (xG {home_xg:.1f} vs {away_xg:.1f}).")
        else:
            parts.append(f"ניצחון צמוד ל{home_label} — יתרון קל בהתקפה הצפויה.")
    else:
        margin = a - h
        if margin >= 2:
            parts.append(f"{away_label} שולטת עם יתרון התקפי (xG {away_xg:.1f} vs {home_xg:.1f}).")
        else:
            parts.append(f"ניצחון צמוד ל{away_label} — יתרון קל בהתקפה הצפויה.")

    if total_goals >= 4:
        parts.append("משחק פתוח עם ציפייה לריבוי שערים.")
    elif total_goals <= 1:
        parts.append("משחק שמרני עם מעט שערים צפויים.")

    if abs(xg_gap) < 0.25 and h != a:
        parts.append("כוחות דומים — תוצאה צמודה מתאימה לפער xG הקטן.")

    return " ".join(parts)


def explain_outcome_1x2(
    outcome: str,
    probability: float,
    *,
    home_power: float,
    away_power: float,
    home_xg: float,
    away_xg: float,
    home_team: str,
    away_team: str,
) -> str:
    home_label = _short_name(home_team)
    away_label = _short_name(away_team)
    power_gap = home_power - away_power

    if outcome == "home":
        if power_gap > 80:
            return (
                f"{home_label} חזקה משמעותית (כוח {home_power:.0f} מול {away_power:.0f}). "
                f"xG צפוי {home_xg:.1f}–{away_xg:.1f}. הסתברות {probability:.1f}%."
            )
        if power_gap > 20:
            return (
                f"יתרון ל{home_label} בכוח וב-xG ({home_xg:.1f} מול {away_xg:.1f}). "
                f"הסתברות ניצחון {probability:.1f}%."
            )
        return (
            f"ניצחון צמוד ל{home_label} — פער כוח קטן ({power_gap:+.0f} נקודות). "
            f"הסתברות {probability:.1f}%."
        )

    if outcome == "away":
        gap = away_power - home_power
        if gap < -150:
            return (
                f"הפתעה: ניצחון {away_label} רק ב-{probability:.1f}% — "
                f"פער כוח {abs(gap):.0f} נקודות לטובת {home_label}."
            )
        if gap > 80:
            return (
                f"{away_label} חזקה משמעותית (כוח {away_power:.0f} מול {home_power:.0f}). "
                f"xG צפוי {away_xg:.1f}–{home_xg:.1f}. הסתברות {probability:.1f}%."
            )
        if gap > 20:
            return (
                f"יתרון ל{away_label} בכוח וב-xG ({away_xg:.1f} מול {home_xg:.1f}). "
                f"הסתברות ניצחון {probability:.1f}%."
            )
        return (
            f"ניצחון צמוד ל{away_label} — פער כוח קטן. "
            f"הסתברות {probability:.1f}%."
        )

    # draw
    if abs(power_gap) > 150:
        favorite = home_label if power_gap > 0 else away_label
        return (
            f"תיקו ב-{probability:.1f}% למרות יתרון ברור ל{favorite} "
            f"(פער {abs(power_gap):.0f} נקודות). xG {home_xg:.1f}–{away_xg:.1f} — "
            "Dixon-Coles מעלה הסתברות לתוצאות שוויון נמוכות."
        )
    if abs(power_gap) > 50:
        return (
            f"תיקו ב-{probability:.1f}% — כוחות לא שווים (פער {abs(power_gap):.0f}) "
            f"אך xG קרוב ({home_xg:.1f}–{away_xg:.1f}). תיקון Dixon-Coles לתוצאות נמוכות."
        )
    return (
        f"כוחות קרובים (פער {abs(power_gap):.0f} נקודות) ו-xG דומה "
        f"({home_xg:.1f}–{away_xg:.1f}). תיקו מועדף ב-{probability:.1f}% "
        "בזכות תיקון Dixon-Coles לתוצאות נמוכות."
    )


def explain_score_coverage(scores: list[str], achieved_percent: float) -> str:
    if not scores:
        return "לא חושב טווח תוצאות."
    if len(scores) == 1:
        return f"תוצאה {scores[0]} לבדה מכסה {achieved_percent:.0f}% מההסתברות."
    joined = ", ".join(scores[:5])
    extra = f" (+{len(scores) - 5} נוספות)" if len(scores) > 5 else ""
    return (
        f"קבוצת תוצאות ({joined}{extra}) מכסה כ-{achieved_percent:.0f}% "
        "מכל האפשרויות — מומלץ לחשוב בטווח, לא בתוצאה בודדת."
    )


def build_match_summary(
    *,
    home_team: str,
    away_team: str,
    home_power: float,
    away_power: float,
    home_xg: float,
    away_xg: float,
    probs: dict[str, float],
) -> str:
    home_label = _short_name(home_team)
    away_label = _short_name(away_team)
    best = max(
        [("home", probs["home_win"]), ("draw", probs["draw"]), ("away", probs["away_win"])],
        key=lambda x: x[1],
    )
    outcome_he = {"home": f"ניצחון {home_label}", "draw": "תיקו", "away": f"ניצחון {away_label}"}
    total_xg = home_xg + away_xg
    tempo = "גבוה" if total_xg >= 3.2 else "בינוני" if total_xg >= 2.4 else "נמוך"

    return (
        f"צפי מרכזי: {outcome_he[best[0]]} ({best[1]:.1f}%). "
        f"סה\"כ xG ~{total_xg:.1f} (קצב {tempo}). "
        f"כוח: {home_label} {home_power:.0f} | {away_label} {away_power:.0f}."
    )
