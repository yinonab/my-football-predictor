import '../models/prediction_result.dart';
import '../models/venue_mode.dart';
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
  VenueMode? requestedVenueMode,
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
  final diag = result.matchContextDiagnostics;
  final venueNote = homeAdvantageExplanation(diag, requestedVenueMode);

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

  if (venueNote != null) {
    bullets.add(venueNote);
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

String effectiveVenueModeApi(
  MatchContextDiagnostics? diag,
  VenueMode? requested,
) {
  final fromBackend = VenueModeApi.fromApi(diag?.venueMode);
  if (fromBackend != null) return fromBackend.apiValue;
  if (requested != null) return requested.apiValue;
  if (diag != null && !diag.neutralGroundRequested) {
    return VenueMode.firstTeamHome.apiValue;
  }
  return VenueMode.neutral.apiValue;
}

String? venueContextSummaryLine({
  required MatchContextDiagnostics? diag,
  required String homeTeam,
  required String awayTeam,
  VenueMode? requestedVenueMode,
}) {
  if (diag == null && requestedVenueMode == null) return null;

  final mode = effectiveVenueModeApi(diag, requestedVenueMode);
  final home = shortTeamName(homeTeam);
  final away = shortTeamName(awayTeam);

  switch (mode) {
    case 'neutral':
      return 'מיקום המשחק: מגרש ניטרלי — לא נוסף יתרון ביתיות.';
    case 'first_team_home':
      if (diag?.hostAdvantageApplied == true) {
        return 'מיקום המשחק: $home מארחת — נוסף יתרון ביתיות.';
      }
      return 'מיקום המשחק: $home מארחת.';
    case 'second_team_home':
      if (diag?.hostAdvantageApplied == true) {
        return 'מיקום המשחק: $away מארחת — נוסף יתרון ביתיות.';
      }
      return 'מיקום המשחק: $away מארחת.';
    case 'host_country_auto':
      if (diag?.hostAdvantageApplied == true) {
        final team = _advantageTeamLabel(diag!, homeTeam, awayTeam);
        return 'זוהתה מדינה מארחת — נוסף יתרון ביתיות ל־$team.';
      }
      return 'לא זוהתה מדינה מארחת מתאימה — לא נוסף יתרון ביתיות.';
    default:
      return null;
  }
}

String? homeAdvantagePowerDeltaLine(MatchContextDiagnostics? diag) {
  if (diag == null || !diag.hostAdvantageApplied) return null;
  final delta = diag.homeAdvantagePowerDelta;
  if (delta <= 0) return null;
  return 'השפעת ביתיות: +${delta.round()} נקודות כוח';
}

String? homeAdvantageExplanation(
  MatchContextDiagnostics? diag,
  VenueMode? requestedVenueMode,
) {
  if (diag == null) {
    if (requestedVenueMode == VenueMode.neutral) {
      return 'המשחק מוגדר כניטרלי.';
    }
    return null;
  }

  if (diag.hostAdvantageApplied) {
    return 'יתרון ביתיות נכלל בחישוב.';
  }

  final mode = effectiveVenueModeApi(diag, requestedVenueMode);
  if (mode == 'neutral') {
    return 'המשחק מוגדר כניטרלי.';
  }
  if (mode == 'host_country_auto') {
    return 'נתוני מיקום/מדינה מארחת לא היו זמינים — לא נוסף יתרון ביתיות.';
  }

  if (diag.warnings.contains('HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO')) {
    return 'יתרון ביתיות לא נוסף בפועל במודל הנוכחי.';
  }

  return null;
}

String? hostAdvantageNote(MatchContextDiagnostics? diag) {
  return homeAdvantageExplanation(diag, null);
}

String _advantageTeamLabel(
  MatchContextDiagnostics diag,
  String homeTeam,
  String awayTeam,
) {
  final teamKey = diag.homeAdvantageTeam ?? diag.hostAdvantageCandidateTeam;
  if (teamKey == 'away') return shortTeamName(awayTeam);
  if (teamKey == 'home') return shortTeamName(homeTeam);
  if (diag.hostAdvantageCandidateTeam != null &&
      diag.hostAdvantageCandidateTeam!.isNotEmpty) {
    return shortTeamName(diag.hostAdvantageCandidateTeam!);
  }
  return shortTeamName(homeTeam);
}
