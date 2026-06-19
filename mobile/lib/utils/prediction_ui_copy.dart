import '../models/prediction_result.dart';
import 'score_format.dart';

/// Rest-day values from API without a known fixture are misleading (e.g. 713 days).
const int _maxReliableRestDays = 60;

bool isMatchCompletedOrInvalid(PredictionResult result) {
  final diag = result.matchContextDiagnostics;
  if (diag == null) return false;
  return !diag.predictionValid || diag.fixtureStatus == 'completed';
}

bool isFixtureContextReliable(MatchContextDiagnostics? diag) {
  if (diag == null) return false;
  return diag.fixtureSourceAvailable && diag.fixtureStatus != 'unknown';
}

bool shouldShowRestDays(
  MatchContextDiagnostics? diag,
  MatchContextInfo? ctx,
) {
  if (!isFixtureContextReliable(diag) || ctx == null) return false;
  final home = ctx.homeRestDays;
  final away = ctx.awayRestDays;
  if (home == null || away == null) return false;
  return home <= _maxReliableRestDays && away <= _maxReliableRestDays;
}

bool hasContextLimitedWarning(PredictionResult result) {
  final codes = <String>{
    ...?result.scorelineDecision?.warnings,
    ...?result.matchContextDiagnostics?.warnings,
  };
  return codes.contains('CONTEXT_LIMITED') ||
      codes.contains('FIXTURE_STATE_UNAVAILABLE') ||
      codes.contains('EXTERNAL_FIXTURE_SOURCE_UNAVAILABLE');
}

bool hasLiveFixtureUnavailableWarning(PredictionResult result) {
  final codes = <String>{
    ...?result.scorelineDecision?.warnings,
    ...?result.matchContextDiagnostics?.warnings,
  };
  return codes.contains('API_FOOTBALL_ACCOUNT_SUSPENDED') ||
      codes.contains('API_FOOTBALL_UNAVAILABLE');
}

String favoriteOutcomeText({
  required String outcome,
  required String homeTeam,
  required String awayTeam,
}) {
  final home = shortTeamName(homeTeam);
  final away = shortTeamName(awayTeam);
  switch (outcome) {
    case 'home_win':
      return 'ניצחון $home';
    case 'away_win':
      return 'ניצחון $away';
    case 'draw':
      return 'תיקו';
    default:
      return outcome;
  }
}

String formatScorelineCandidate(
  ScorelineCandidate candidate, {
  required String homeTeam,
  required String awayTeam,
  bool isNeutralGround = true,
}) {
  return formatNamedScore(
    '${candidate.homeGoals}-${candidate.awayGoals}',
    teamAName: homeTeam,
    teamBName: awayTeam,
    isNeutralGround: isNeutralGround,
  );
}

List<String> buildWhyPredictionBullets(
  PredictionResult result, {
  required bool neutralGround,
}) {
  final sd = result.scorelineDecision;
  if (sd != null && sd.primaryScoreReason.trim().isNotEmpty) {
    final reason = sd.primaryScoreReason.trim();
    if (reason.length <= 220) {
      return [reason];
    }
    return ['${reason.substring(0, 217).trimRight()}…'];
  }

  final bullets = <String>[];
  final probs = result.probabilities;
  final home = shortTeamName(result.homeTeam);
  final away = shortTeamName(result.awayTeam);

  if (probs.homeWin >= probs.draw && probs.homeWin >= probs.awayWin) {
    bullets.add('$home היא הפייבוריטית לפי המודל (${probs.homeWin.toStringAsFixed(1)}%).');
  } else if (probs.awayWin >= probs.draw) {
    bullets.add('$away היא הפייבוריטית לפי המודל (${probs.awayWin.toStringAsFixed(1)}%).');
  } else {
    bullets.add('המודל מעריך שהמשחק מאוזן יחסית (תיקו ${probs.draw.toStringAsFixed(1)}%).');
  }

  if (result.homeXg > result.awayXg + 0.15) {
    bullets.add('המודל נותן ל$home יתרון צפוי בשערים (xG).');
  } else if (result.awayXg > result.homeXg + 0.15) {
    bullets.add('המודל נותן ל$away יתרון צפוי בשערים (xG).');
  }

  if (neutralGround) {
    bullets.add('המשחק מוגדר כניטרלי, לכן לא נוסף יתרון ביתיות.');
  } else {
    bullets.add('הקבוצה הראשונה מארחת — יתרון ביתיות מופעל בהגדרות.');
  }

  if (hasContextLimitedWarning(result) || hasLiveFixtureUnavailableWarning(result)) {
    bullets.add('חלק מנתוני ההקשר של המשחק אינם זמינים, לכן רמת הביטחון מוגבלת.');
  }

  return bullets;
}

List<String> buildUserWarningLines(PredictionResult result) {
  final lines = <String>[];
  final sd = result.scorelineDecision;

  if (sd?.confidenceLabel == 'low') {
    lines.add('רמת ביטחון נמוכה');
  }

  if (hasContextLimitedWarning(result)) {
    lines.add('תחזית מוגבלת — חלק מנתוני המשחק אינם זמינים.');
  } else if (hasLiveFixtureUnavailableWarning(result)) {
    lines.add('נתוני משחק חיים אינם זמינים כרגע.');
  }

  return lines;
}

String neutralToggleSubtitle({
  required bool neutralGround,
  required String homeTeam,
}) {
  if (neutralGround) {
    return 'מגרש ניטרלי — אין יתרון ביתיות';
  }
  return 'הקבוצה הראשונה מארחת — ${shortTeamName(homeTeam)} מקבלת יתרון ביתיות';
}

String? hostAdvantageNote(MatchContextDiagnostics? diag) {
  if (diag == null) return null;
  final warnings = diag.warnings;
  if (warnings.contains('HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO') ||
      (!diag.hostAdvantageApplied && diag.homeAdvantageValue <= 0)) {
    return 'יתרון ביתיות לא נוסף בפועל במודל הנוכחי.';
  }
  return null;
}
