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

const String kLabelFavoriteStillWins =
    'אם האנדרדוג כובש והפייבוריט עדיין מנצחת';
const String kLabelMostLikelyUnderdogScores =
    'התרחיש הסביר ביותר שבו האנדרדוג כובש';
const String kLabelIllustrationFavoriteWins =
    'תרחיש המחשה אם האנדרדוג כובש והפייבוריט עדיין מנצחת';

class UnderdogScoringAlternativeLine {
  final String label;
  final String scoreText;
  final double? probabilityPercent;
  final bool isIllustration;

  const UnderdogScoringAlternativeLine({
    required this.label,
    required this.scoreText,
    this.probabilityPercent,
    this.isIllustration = false,
  });
}

class UnderdogScoringNarrative {
  final String primaryScoreText;
  final String underdogTeamName;
  final String favoriteTeamName;
  final double underdogScoringProbabilityPercent;
  final double? bttsProbabilityPercent;
  final List<UnderdogScoringAlternativeLine> alternativeLines;

  const UnderdogScoringNarrative({
    required this.primaryScoreText,
    required this.underdogTeamName,
    required this.favoriteTeamName,
    required this.underdogScoringProbabilityPercent,
    required this.alternativeLines,
    this.bttsProbabilityPercent,
  });

  /// Back-compat for tests referencing a single alternative string.
  String get alternativeScoreText =>
      alternativeLines.isNotEmpty ? alternativeLines.first.scoreText : '';
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

(int, int)? _scoreGoals(String score) {
  final home = _parseGoals(score, home: true);
  final away = _parseGoals(score, home: false);
  if (home == null || away == null) return null;
  return (home, away);
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
  final goals = _scoreGoals(score);
  if (goals == null) return false;
  final (home, away) = goals;
  switch (favoriteOutcome) {
    case 'home_win':
      return home > away;
    case 'away_win':
      return away > home;
    default:
      return false;
  }
}

bool isDrawScore(String score) {
  final goals = _scoreGoals(score);
  if (goals == null) return false;
  return goals.$1 == goals.$2;
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

int _favoriteGoalsInScore(String score, String favoriteOutcome) {
  final goals = _scoreGoals(score);
  if (goals == null) return 0;
  switch (favoriteOutcome) {
    case 'home_win':
      return goals.$1;
    case 'away_win':
      return goals.$2;
    default:
      return 0;
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

String _favoriteTeamName(PredictionResult result, String favoriteOutcome) {
  switch (favoriteOutcome) {
    case 'home_win':
      return shortTeamName(result.homeTeam);
    case 'away_win':
      return shortTeamName(result.awayTeam);
    default:
      return result.homeXg >= result.awayXg
          ? shortTeamName(result.homeTeam)
          : shortTeamName(result.awayTeam);
  }
}

class _ScoreCandidate {
  final String score;
  final double? probability;

  const _ScoreCandidate({required this.score, this.probability});
}

List<_ScoreCandidate> _collectScoreCandidates(PredictionResult result) {
  final byScore = <String, _ScoreCandidate>{};

  void add(String score, double? probability) {
    final existing = byScore[score];
    if (existing == null) {
      byScore[score] = _ScoreCandidate(score: score, probability: probability);
      return;
    }
    if (probability != null &&
        (existing.probability == null || probability > existing.probability!)) {
      byScore[score] = _ScoreCandidate(score: score, probability: probability);
    }
  }

  for (final s in result.topScores) {
    add(s.score, s.probability);
  }

  final sd = result.scorelineDecision;
  if (sd != null) {
    for (final c in sd.favoriteOutcomeTopScores) {
      add('${c.homeGoals}-${c.awayGoals}', c.probability);
    }
    final bestUd =
        sd.candidateComparisonSummary['best_underdog_goal_candidate'];
    if (bestUd is String && bestUd.isNotEmpty) {
      add(bestUd, byScore[bestUd]?.probability);
    }
  }

  return byScore.values.toList();
}

_ScoreCandidate? _bestFavoriteWinCandidate(
  List<_ScoreCandidate> candidates,
  String favoriteOutcome,
  int primaryFavoriteGoals,
) {
  final favWins = candidates.where((c) {
    if (underdogGoalsInScore(c.score, favoriteOutcome) < 1) return false;
    return isFavoriteWinScore(c.score, favoriteOutcome);
  }).toList();
  if (favWins.isEmpty) return null;

  favWins.sort((a, b) {
    final aGoals = _favoriteGoalsInScore(a.score, favoriteOutcome);
    final bGoals = _favoriteGoalsInScore(b.score, favoriteOutcome);
    final aDist = (aGoals - primaryFavoriteGoals).abs();
    final bDist = (bGoals - primaryFavoriteGoals).abs();
    if (aDist != bDist) return aDist.compareTo(bDist);
    final aUd = underdogGoalsInScore(a.score, favoriteOutcome);
    final bUd = underdogGoalsInScore(b.score, favoriteOutcome);
    if (aUd == 1 && bUd != 1) return -1;
    if (bUd == 1 && aUd != 1) return 1;
    final aProb = a.probability ?? 0;
    final bProb = b.probability ?? 0;
    return bProb.compareTo(aProb);
  });
  return favWins.first;
}

_ScoreCandidate? _bestDrawCandidate(
  List<_ScoreCandidate> candidates,
  String favoriteOutcome,
) {
  final draws = candidates
      .where(
        (c) =>
            isDrawScore(c.score) &&
            underdogGoalsInScore(c.score, favoriteOutcome) >= 1,
      )
      .toList();
  if (draws.isEmpty) return null;
  draws.sort(
    (a, b) => (b.probability ?? 0).compareTo(a.probability ?? 0),
  );
  return draws.first;
}

_ScoreCandidate? _bestAnyUnderdogScoring(
  List<_ScoreCandidate> candidates,
  String favoriteOutcome,
) {
  final withUd = candidates
      .where((c) => underdogGoalsInScore(c.score, favoriteOutcome) >= 1)
      .toList();
  if (withUd.isEmpty) return null;
  withUd.sort(
    (a, b) => (b.probability ?? 0).compareTo(a.probability ?? 0),
  );
  return withUd.first;
}

String _contextualFavoriteWinScore(
  ScorelineCandidate primary,
  String favoriteOutcome,
) {
  switch (favoriteOutcome) {
    case 'home_win':
      return '${primary.homeGoals}-1';
    case 'away_win':
      return '1-${primary.awayGoals}';
    default:
      return '${primary.homeGoals}-1';
  }
}

String _formatScore(
  PredictionResult result,
  String score, {
  required bool isNeutralGround,
}) {
  return formatNamedScore(
    score,
    teamAName: result.homeTeam,
    teamBName: result.awayTeam,
    isNeutralGround: isNeutralGround,
  );
}

UnderdogScoringAlternativeLine _lineFromCandidate(
  _ScoreCandidate candidate,
  PredictionResult result, {
  required String label,
  required bool isNeutralGround,
  bool isIllustration = false,
}) {
  return UnderdogScoringAlternativeLine(
    label: label,
    scoreText: _formatScore(result, candidate.score, isNeutralGround: isNeutralGround),
    probabilityPercent: isIllustration ? null : candidate.probability,
    isIllustration: isIllustration,
  );
}

List<UnderdogScoringAlternativeLine> _buildAlternativeLines({
  required PredictionResult result,
  required ScorelineCandidate primary,
  required String favoriteOutcome,
  required List<_ScoreCandidate> candidates,
  required bool isNeutralGround,
}) {
  final primaryFavGoals = favoriteOutcome == 'home_win'
      ? primary.homeGoals
      : primary.awayGoals;
  final favoriteName = _favoriteTeamName(result, favoriteOutcome);

  final bestFavWin = _bestFavoriteWinCandidate(
    candidates,
    favoriteOutcome,
    primaryFavGoals,
  );
  final bestDraw = _bestDrawCandidate(candidates, favoriteOutcome);

  final lines = <UnderdogScoringAlternativeLine>[];

  if (primaryFavGoals >= 2 && bestFavWin != null) {
    lines.add(
      _lineFromCandidate(
        bestFavWin,
        result,
        label: kLabelFavoriteStillWins,
        isNeutralGround: isNeutralGround,
      ),
    );
    return lines;
  }

  if (primaryFavGoals == 1 && bestDraw != null && bestFavWin != null) {
    lines.add(
      _lineFromCandidate(
        bestDraw,
        result,
        label: kLabelMostLikelyUnderdogScores,
        isNeutralGround: isNeutralGround,
      ),
    );
    lines.add(
      _lineFromCandidate(
        bestFavWin,
        result,
        label: kLabelFavoriteStillWins,
        isNeutralGround: isNeutralGround,
      ),
    );
    return lines;
  }

  if (bestFavWin != null) {
    lines.add(
      _lineFromCandidate(
        bestFavWin,
        result,
        label: kLabelFavoriteStillWins,
        isNeutralGround: isNeutralGround,
      ),
    );
    return lines;
  }

  if (bestDraw != null) {
    lines.add(
      _lineFromCandidate(
        bestDraw,
        result,
        label: kLabelMostLikelyUnderdogScores,
        isNeutralGround: isNeutralGround,
      ),
    );

    if (primaryFavGoals >= 1) {
      final contextual = _contextualFavoriteWinScore(primary, favoriteOutcome);
      _ScoreCandidate? contextualCandidate;
      for (final c in candidates) {
        if (c.score == contextual) {
          contextualCandidate = c;
          break;
        }
      }

      if (contextualCandidate != null &&
          isFavoriteWinScore(contextualCandidate.score, favoriteOutcome)) {
        lines.add(
          _lineFromCandidate(
            contextualCandidate,
            result,
            label: 'אם $favoriteName עדיין מנצחת',
            isNeutralGround: isNeutralGround,
          ),
        );
      } else {
        lines.add(
          UnderdogScoringAlternativeLine(
            label: kLabelIllustrationFavoriteWins,
            scoreText: _formatScore(
              result,
              contextual,
              isNeutralGround: isNeutralGround,
            ),
            isIllustration: true,
          ),
        );
      }
    }
    return lines;
  }

  return lines;
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

  final candidates = _collectScoreCandidates(result);
  final bestUd = _bestAnyUnderdogScoring(candidates, favorite);
  if (bestUd == null) return null;

  final rank = rankInTopScores(result.topScores, bestUd.score);
  final primaryProb = primary.probability;
  final probGap = (primaryProb - (bestUd.probability ?? 0)).abs();
  final isClose = probGap <= closeProbGapPp;
  final rankQualifies = rank != null && rank <= maxRank;
  final probQualifies = udProb >= minProbability;

  if (!probQualifies && !rankQualifies && !isClose) return null;

  final alternativeLines = _buildAlternativeLines(
    result: result,
    primary: primary,
    favoriteOutcome: favorite,
    candidates: candidates,
    isNeutralGround: isNeutralGround,
  );
  if (alternativeLines.isEmpty) return null;

  return UnderdogScoringNarrative(
    primaryScoreText: formatScorelineCandidate(
      primary,
      homeTeam: result.homeTeam,
      awayTeam: result.awayTeam,
      isNeutralGround: isNeutralGround,
    ),
    underdogTeamName: _underdogTeamName(result, favorite),
    favoriteTeamName: _favoriteTeamName(result, favorite),
    underdogScoringProbabilityPercent: udProb,
    alternativeLines: alternativeLines,
    bttsProbabilityPercent: sd.bothTeamsScoreProbability,
  );
}

/// Shown under top_scores when primary differs from the modal exact score.
bool shouldShowTopScoresRepresentativeNote(PredictionResult result) {
  final sd = result.scorelineDecision;
  if (sd == null) return false;
  if (sd.topExactScoreDiffersFromPrimary) return true;
  final primary = sd.primaryPredictedScore;
  if (primary == null || result.topScores.isEmpty) return false;
  final topLabel = result.topScores.first.score;
  final primaryLabel = '${primary.homeGoals}-${primary.awayGoals}';
  return topLabel != primaryLabel;
}

const String kTopScoresRepresentativeNote =
    'התחזית המרכזית נבחרת לפי שקלול המודל, לא רק לפי ההסתברות הגולמית של תוצאה בודדת.';
