import 'dart:math' show exp;

import '../models/prediction_result.dart';
import 'prediction_ui_copy.dart';
import 'score_format.dart';

/// Minimum matrix-derived underdog scoring probability to show narrative.
const double kUnderdogScoringNarrativeMinProbability = 40.0;

/// Rank in [top_scores] (1-based) that qualifies for display.
const int kUnderdogScoringNarrativeMaxRank = 5;

/// Probability gap (percentage points) between primary and best ud-scoring line.
const double kUnderdogScoringCloseProbGapPp = 3.5;

class UnderdogScoringNarrative {
  final String primaryScoreText;
  final String underdogTeamName;
  final double underdogScoringProbabilityPercent;
  final String alternativeScoreText;
  final double? bttsProbabilityPercent;

  const UnderdogScoringNarrative({
    required this.primaryScoreText,
    required this.underdogTeamName,
    required this.underdogScoringProbabilityPercent,
    required this.alternativeScoreText,
    this.bttsProbabilityPercent,
  });
}

/// Display-only Poisson estimate when API omits matrix probability.
double poissonUnderdogScoresProbabilityPercent(double underdogXg) {
  return (1 - exp(-underdogXg)) * 100;
}

int? _parseGoals(String score, {required bool home}) {
  final parts = score.split('-');
  if (parts.length != 2) return null;
  final raw = home ? parts[0].trim() : parts[1].trim();
  return int.tryParse(raw);
}

int underdogGoalsInScore(String score, String favoriteOutcome) {
  switch (favoriteOutcome) {
    case 'home_win':
      return _parseGoals(score, home: false) ?? 0;
    case 'away_win':
      return _parseGoals(score, home: true) ?? 0;
    default:
      return 0;
  }
}

bool isFavoriteWinScore(String score, String favoriteOutcome) {
  final parts = score.split('-');
  if (parts.length != 2) return false;
  final home = int.tryParse(parts[0].trim());
  final away = int.tryParse(parts[1].trim());
  if (home == null || away == null) return false;
  switch (favoriteOutcome) {
    case 'home_win':
      return home > away;
    case 'away_win':
      return away > home;
    default:
      return false;
  }
}

bool isPrimaryCleanSheetForFavorite(
  ScorelineCandidate primary,
  String favoriteOutcome,
) {
  switch (favoriteOutcome) {
    case 'home_win':
      return primary.awayGoals == 0;
    case 'away_win':
      return primary.homeGoals == 0;
    default:
      return false;
  }
}

double _underdogXg(PredictionResult result, String favoriteOutcome) {
  switch (favoriteOutcome) {
    case 'home_win':
      return result.awayXg;
    case 'away_win':
      return result.homeXg;
    default:
      return result.homeXg < result.awayXg ? result.homeXg : result.awayXg;
  }
}

String _underdogTeamName(PredictionResult result, String favoriteOutcome) {
  switch (favoriteOutcome) {
    case 'home_win':
      return shortTeamName(result.awayTeam);
    case 'away_win':
      return shortTeamName(result.homeTeam);
    default:
      return result.homeXg <= result.awayXg
          ? shortTeamName(result.homeTeam)
          : shortTeamName(result.awayTeam);
  }
}

ScoreProbability? _bestUnderdogScoringFromTopScores(
  List<ScoreProbability> topScores,
  String favoriteOutcome, {
  required bool preferFavoriteWin,
}) {
  final withUdGoal = topScores
      .where((s) => underdogGoalsInScore(s.score, favoriteOutcome) >= 1)
      .toList();
  if (withUdGoal.isEmpty) return null;

  if (preferFavoriteWin) {
    final favWin = withUdGoal
        .where((s) => isFavoriteWinScore(s.score, favoriteOutcome))
        .toList();
    if (favWin.isNotEmpty) {
      favWin.sort((a, b) => b.probability.compareTo(a.probability));
      return favWin.first;
    }
  }

  final sorted = List<ScoreProbability>.from(withUdGoal)
    ..sort((a, b) => b.probability.compareTo(a.probability));
  return sorted.first;
}

int? rankInTopScores(List<ScoreProbability> topScores, String scoreLabel) {
  final index = topScores.indexWhere((s) => s.score == scoreLabel);
  if (index < 0) return null;
  return index + 1;
}

bool shouldShowUnderdogScoringNarrative(
  PredictionResult result, {
  double minProbability = kUnderdogScoringNarrativeMinProbability,
  int maxRank = kUnderdogScoringNarrativeMaxRank,
  double closeProbGapPp = kUnderdogScoringCloseProbGapPp,
}) {
  return buildUnderdogScoringNarrative(
        result,
        minProbability: minProbability,
        maxRank: maxRank,
        closeProbGapPp: closeProbGapPp,
      ) !=
      null;
}

/// Builds display-only narrative; does not mutate [result] or reorder [topScores].
UnderdogScoringNarrative? buildUnderdogScoringNarrative(
  PredictionResult result, {
  bool isNeutralGround = true,
  double minProbability = kUnderdogScoringNarrativeMinProbability,
  int maxRank = kUnderdogScoringNarrativeMaxRank,
  double closeProbGapPp = kUnderdogScoringCloseProbGapPp,
}) {
  final sd = result.scorelineDecision;
  final primary = sd?.primaryPredictedScore;
  if (sd == null || primary == null) return null;

  final favorite = sd.favoriteOutcome;
  if (!isPrimaryCleanSheetForFavorite(primary, favorite)) return null;

  final udProb = sd.underdogScoresProbability ??
      poissonUnderdogScoresProbabilityPercent(_underdogXg(result, favorite));

  final bestUd = _bestUnderdogScoringFromTopScores(
    result.topScores,
    favorite,
    preferFavoriteWin: true,
  );
  if (bestUd == null) return null;

  final rank = rankInTopScores(result.topScores, bestUd.score);
  final primaryProb = primary.probability;
  final probGap = (primaryProb - bestUd.probability).abs();
  final isClose = probGap <= closeProbGapPp;
  final rankQualifies = rank != null && rank <= maxRank;
  final probQualifies = udProb >= minProbability;

  if (!probQualifies && !rankQualifies && !isClose) return null;

  final primaryText = formatScorelineCandidate(
    primary,
    homeTeam: result.homeTeam,
    awayTeam: result.awayTeam,
    isNeutralGround: isNeutralGround,
  );
  final alternativeText = formatNamedScore(
    bestUd.score,
    teamAName: result.homeTeam,
    teamBName: result.awayTeam,
    isNeutralGround: isNeutralGround,
  );

  return UnderdogScoringNarrative(
    primaryScoreText: primaryText,
    underdogTeamName: _underdogTeamName(result, favorite),
    underdogScoringProbabilityPercent: udProb,
    alternativeScoreText: alternativeText,
    bttsProbabilityPercent: sd.bothTeamsScoreProbability,
  );
}
