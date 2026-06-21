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

/// One friendly banner when data is limited — shown once on the results page.
String? buildConsolidatedDataLimitMessage(PredictionResult result) {
  if (isMatchCompletedOrInvalid(result)) return null;

  if (hasContextLimitedWarning(result) || hasLiveFixtureUnavailableWarning(result)) {
    return 'חלק מנתוני המשחק חסרים, לכן רמת הביטחון נמוכה יותר.';
  }

  if (result.scorelineDecision?.confidenceLabel == 'low') {
    return 'רמת הביטחון בתחזית נמוכה יחסית.';
  }

  return null;
}

bool shouldShowMatchContextCard(
  PredictionResult result, {
  VenueMode? requestedVenueMode,
}) {
  if (isMatchCompletedOrInvalid(result)) return false;

  final diag = result.matchContextDiagnostics;
  final ctx = result.matchContext;

  if (shouldShowRestDays(diag, ctx)) return true;
  if (ctx?.weatherSummary != null && ctx!.weatherSummary!.isNotEmpty) {
    return true;
  }
  if (diag?.hostAdvantageApplied == true) return true;

  final mode = effectiveVenueModeApi(diag, requestedVenueMode);
  return mode == 'first_team_home' ||
      mode == 'second_team_home' ||
      mode == 'host_country_auto';
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
    final reason = _simplifyPrimaryReason(sd.primaryScoreReason.trim());
    if (reason.length <= 180) {
      return [reason];
    }
    return ['${reason.substring(0, 177).trimRight()}…'];
  }

  final bullets = <String>[];
  final probs = result.probabilities;
  final home = shortTeamName(result.homeTeam);
  final away = shortTeamName(result.awayTeam);
  final venueNote = homeAdvantageExplanation(diag: result.matchContextDiagnostics, requestedVenueMode: requestedVenueMode);

  if (probs.homeWin >= probs.draw && probs.homeWin >= probs.awayWin) {
    bullets.add('$home מובילה בהסתברות (${probs.homeWin.toStringAsFixed(1)}%).');
  } else if (probs.awayWin >= probs.draw) {
    bullets.add('$away מובילה בהסתברות (${probs.awayWin.toStringAsFixed(1)}%).');
  } else {
    bullets.add('המשחק נראה מאוזן (${probs.draw.toStringAsFixed(1)}% לתיקו).');
  }

  if (result.homeXg > result.awayXg + 0.15) {
    bullets.add('$home צפויה להיות מבקיעה יותר.');
  } else if (result.awayXg > result.homeXg + 0.15) {
    bullets.add('$away צפויה להיות מבקיעה יותר.');
  }

  if (venueNote != null) {
    bullets.add(venueNote);
  }

  return bullets;
}

String _simplifyPrimaryReason(String reason) {
  return reason
      .replaceAll('Dixon-Coles', 'המודל')
      .replaceAll('xG', 'שערים צפויים')
      .replaceAll('BTTS', 'שני הקבוצות מבקיעות');
}

List<String> buildUserWarningLines(PredictionResult result) {
  final message = buildConsolidatedDataLimitMessage(result);
  if (message == null) return const [];
  return [message];
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
      return 'מגרש ניטרלי — אין יתרון ביתיות.';
    case 'first_team_home':
      if (diag?.hostAdvantageApplied == true) {
        return '$home מארחת — נוסף יתרון ביתיות.';
      }
      return '$home מארחת.';
    case 'second_team_home':
      if (diag?.hostAdvantageApplied == true) {
        return '$away מארחת — נוסף יתרון ביתיות.';
      }
      return '$away מארחת.';
    case 'host_country_auto':
      if (diag?.hostAdvantageApplied == true) {
        final team = _advantageTeamLabel(diag!, homeTeam, awayTeam);
        return 'מדינה מארחת — יתרון ביתיות ל־$team.';
      }
      return 'לא זוהתה מדינה מארחת — אין יתרון ביתיות.';
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

String? homeAdvantageExplanation({
  MatchContextDiagnostics? diag,
  VenueMode? requestedVenueMode,
}) {
  if (diag == null) {
    if (requestedVenueMode == VenueMode.neutral) {
      return 'מגרש ניטרלי — אין יתרון ביתיות.';
    }
    return null;
  }

  if (diag.hostAdvantageApplied) {
    return 'יתרון ביתיות נכלל בחישוב.';
  }

  final mode = effectiveVenueModeApi(diag, requestedVenueMode);
  if (mode == 'neutral') {
    return 'מגרש ניטרלי — אין יתרון ביתיות.';
  }
  if (mode == 'host_country_auto') {
    return 'לא נמצאו נתוני מיקום מספיקים — לא נוסף יתרון ביתיות.';
  }

  if (diag.warnings.contains('HOST_ADVANTAGE_DETECTED_BUT_VALUE_ZERO')) {
    return 'יתרון ביתיות לא נוסף בחישוב.';
  }

  return null;
}

String? hostAdvantageNote(MatchContextDiagnostics? diag) {
  return homeAdvantageExplanation(diag: diag);
}

List<MapEntry<String, String>> parseBreakdownRows(String breakdown) {
  if (breakdown.trim().isEmpty) return const [];

  final rows = <MapEntry<String, String>>[];
  for (final part in breakdown.split(RegExp(r'[|•\n]'))) {
    final segment = part.trim();
    if (segment.isEmpty) continue;

    final colon = segment.indexOf(':');
    if (colon > 0 && colon < segment.length - 1) {
      rows.add(MapEntry(segment.substring(0, colon).trim(), segment.substring(colon + 1).trim()));
    } else {
      rows.add(MapEntry('פירוט', segment));
    }
  }
  return rows;
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
