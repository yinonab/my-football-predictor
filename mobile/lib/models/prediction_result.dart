import '../config/api_config.dart';

class ScoreProbability {
  final String score;
  final double probability;
  final String explanation;

  const ScoreProbability({
    required this.score,
    required this.probability,
    this.explanation = '',
  });

  factory ScoreProbability.fromJson(Map<String, dynamic> json) {
    return ScoreProbability(
      score: json['score'] as String,
      probability: (json['probability'] as num).toDouble(),
      explanation: json['explanation'] as String? ?? '',
    );
  }
}

class ScoreCoverage {
  final double targetPercent;
  final double achievedPercent;
  final List<String> scores;
  final String explanation;

  const ScoreCoverage({
    required this.targetPercent,
    required this.achievedPercent,
    required this.scores,
    this.explanation = '',
  });

  factory ScoreCoverage.fromJson(Map<String, dynamic> json) {
    return ScoreCoverage(
      targetPercent: (json['target_percent'] as num).toDouble(),
      achievedPercent: (json['achieved_percent'] as num).toDouble(),
      scores: List<String>.from(json['scores'] as List<dynamic>),
      explanation: json['explanation'] as String? ?? '',
    );
  }
}

class OutcomeExplanations {
  final String homeWin;
  final String draw;
  final String awayWin;

  const OutcomeExplanations({
    required this.homeWin,
    required this.draw,
    required this.awayWin,
  });

  factory OutcomeExplanations.fromJson(Map<String, dynamic> json) {
    return OutcomeExplanations(
      homeWin: json['home_win'] as String,
      draw: json['draw'] as String,
      awayWin: json['away_win'] as String,
    );
  }
}

class Probabilities1X2 {
  final double homeWin;
  final double draw;
  final double awayWin;

  const Probabilities1X2({
    required this.homeWin,
    required this.draw,
    required this.awayWin,
  });

  factory Probabilities1X2.fromJson(Map<String, dynamic> json) {
    return Probabilities1X2(
      homeWin: (json['home_win'] as num).toDouble(),
      draw: (json['draw'] as num).toDouble(),
      awayWin: (json['away_win'] as num).toDouble(),
    );
  }
}

class TeamBreakdown {
  final String name;
  final double powerScore;
  final double elo;
  final String breakdown;
  final String? group;

  const TeamBreakdown({
    required this.name,
    required this.powerScore,
    required this.elo,
    required this.breakdown,
    this.group,
  });

  factory TeamBreakdown.fromJson(Map<String, dynamic> json) {
    return TeamBreakdown(
      name: json['name'] as String,
      powerScore: (json['power_score'] as num).toDouble(),
      elo: (json['elo'] as num).toDouble(),
      breakdown: json['breakdown'] as String,
      group: json['group'] as String?,
    );
  }
}

class MatchContextInfo {
  final bool enabled;
  final String dataSource;
  final int? homeRestDays;
  final int? awayRestDays;
  final String? homeLastCity;
  final String? awayLastCity;
  final String? venueCity;
  final String? matchDate;
  final String? stage;
  final double? awayTravelKm;
  final double? homeTravelKm;
  final String? weatherSummary;
  final double? weatherTempC;
  final double? weatherRainMm;
  final double homePowerMult;
  final double awayPowerMult;
  final double xgTotalDelta;
  final List<String> notes;

  const MatchContextInfo({
    this.enabled = true,
    this.dataSource = 'offline',
    this.homeRestDays,
    this.awayRestDays,
    this.homeLastCity,
    this.awayLastCity,
    this.venueCity,
    this.matchDate,
    this.stage,
    this.awayTravelKm,
    this.homeTravelKm,
    this.weatherSummary,
    this.weatherTempC,
    this.weatherRainMm,
    this.homePowerMult = 1.0,
    this.awayPowerMult = 1.0,
    this.xgTotalDelta = 0.0,
    this.notes = const [],
  });

  bool get hasDetails =>
      notes.isNotEmpty ||
      weatherSummary != null ||
      homeRestDays != null ||
      awayRestDays != null;

  factory MatchContextInfo.fromJson(Map<String, dynamic> json) {
    return MatchContextInfo(
      enabled: json['enabled'] as bool? ?? true,
      dataSource: json['data_source'] as String? ?? 'offline',
      homeRestDays: json['home_rest_days'] as int?,
      awayRestDays: json['away_rest_days'] as int?,
      homeLastCity: json['home_last_city'] as String?,
      awayLastCity: json['away_last_city'] as String?,
      venueCity: json['venue_city'] as String?,
      matchDate: json['match_date'] as String?,
      stage: json['stage'] as String?,
      awayTravelKm: (json['away_travel_km'] as num?)?.toDouble(),
      homeTravelKm: (json['home_travel_km'] as num?)?.toDouble(),
      weatherSummary: json['weather_summary'] as String?,
      weatherTempC: (json['weather_temp_c'] as num?)?.toDouble(),
      weatherRainMm: (json['weather_rain_mm'] as num?)?.toDouble(),
      homePowerMult: (json['home_power_mult'] as num?)?.toDouble() ?? 1.0,
      awayPowerMult: (json['away_power_mult'] as num?)?.toDouble() ?? 1.0,
      xgTotalDelta: (json['xg_total_delta'] as num?)?.toDouble() ?? 0.0,
      notes: List<String>.from(json['notes'] as List<dynamic>? ?? []),
    );
  }
}

class ScorelineCandidate {
  final int homeGoals;
  final int awayGoals;
  final double probability;
  final String outcome;

  const ScorelineCandidate({
    required this.homeGoals,
    required this.awayGoals,
    required this.probability,
    required this.outcome,
  });

  factory ScorelineCandidate.fromJson(Map<String, dynamic> json) {
    return ScorelineCandidate(
      homeGoals: json['home_goals'] as int,
      awayGoals: json['away_goals'] as int,
      probability: (json['probability'] as num).toDouble(),
      outcome: json['outcome'] as String,
    );
  }
}

class ScorelineDecision {
  final String favoriteOutcome;
  final double favoriteOutcomeProbability;
  final String secondOutcome;
  final double secondOutcomeProbability;
  final double outcomeMargin;
  final String confidenceLabel;
  final ScorelineCandidate? primaryPredictedScore;
  final String primaryScoreReason;
  final ScorelineCandidate? topExactScoreOverall;
  final bool topExactScoreDiffersFromPrimary;
  final List<ScorelineCandidate> favoriteOutcomeTopScores;
  final List<String> warnings;

  const ScorelineDecision({
    required this.favoriteOutcome,
    required this.favoriteOutcomeProbability,
    required this.secondOutcome,
    required this.secondOutcomeProbability,
    required this.outcomeMargin,
    required this.confidenceLabel,
    this.primaryPredictedScore,
    this.primaryScoreReason = '',
    this.topExactScoreOverall,
    this.topExactScoreDiffersFromPrimary = false,
    this.favoriteOutcomeTopScores = const [],
    this.warnings = const [],
  });

  factory ScorelineDecision.fromJson(Map<String, dynamic> json) {
    return ScorelineDecision(
      favoriteOutcome: json['favorite_outcome'] as String,
      favoriteOutcomeProbability:
          (json['favorite_outcome_probability'] as num).toDouble(),
      secondOutcome: json['second_outcome'] as String,
      secondOutcomeProbability:
          (json['second_outcome_probability'] as num).toDouble(),
      outcomeMargin: (json['outcome_margin'] as num).toDouble(),
      confidenceLabel: json['confidence_label'] as String? ?? 'medium',
      primaryPredictedScore: json['primary_predicted_score'] != null
          ? ScorelineCandidate.fromJson(
              json['primary_predicted_score'] as Map<String, dynamic>,
            )
          : null,
      primaryScoreReason: json['primary_score_reason'] as String? ?? '',
      topExactScoreOverall: json['top_exact_score_overall'] != null
          ? ScorelineCandidate.fromJson(
              json['top_exact_score_overall'] as Map<String, dynamic>,
            )
          : null,
      topExactScoreDiffersFromPrimary:
          json['top_exact_score_differs_from_primary'] as bool? ?? false,
      favoriteOutcomeTopScores:
          (json['favorite_outcome_top_scores'] as List<dynamic>? ?? [])
              .map(
                (e) => ScorelineCandidate.fromJson(e as Map<String, dynamic>),
              )
              .toList(),
      warnings: List<String>.from(json['warnings'] as List<dynamic>? ?? []),
    );
  }
}

class ActualScore {
  final int home;
  final int away;

  const ActualScore({required this.home, required this.away});

  factory ActualScore.fromJson(Map<String, dynamic> json) {
    return ActualScore(
      home: json['home'] as int,
      away: json['away'] as int,
    );
  }
}

class MatchContextDiagnostics {
  final String fixtureStatus;
  final bool predictionValid;
  final String predictionMode;
  final ActualScore? actualScore;
  final bool fixtureSourceAvailable;
  final bool venueContextAvailable;
  final bool neutralGroundRequested;
  final bool hostAdvantageApplied;
  final double homeAdvantageValue;
  final List<String> warnings;

  const MatchContextDiagnostics({
    this.fixtureStatus = 'unknown',
    this.predictionValid = true,
    this.predictionMode = 'unknown',
    this.actualScore,
    this.fixtureSourceAvailable = false,
    this.venueContextAvailable = false,
    this.neutralGroundRequested = true,
    this.hostAdvantageApplied = false,
    this.homeAdvantageValue = 0,
    this.warnings = const [],
  });

  factory MatchContextDiagnostics.fromJson(Map<String, dynamic> json) {
    return MatchContextDiagnostics(
      fixtureStatus: json['fixture_status'] as String? ?? 'unknown',
      predictionValid: json['prediction_valid'] as bool? ?? true,
      predictionMode: json['prediction_mode'] as String? ?? 'unknown',
      actualScore: json['actual_score'] != null
          ? ActualScore.fromJson(json['actual_score'] as Map<String, dynamic>)
          : null,
      fixtureSourceAvailable:
          json['fixture_source_available'] as bool? ?? false,
      venueContextAvailable: json['venue_context_available'] as bool? ?? false,
      neutralGroundRequested:
          json['neutral_ground_requested'] as bool? ?? true,
      hostAdvantageApplied: json['host_advantage_applied'] as bool? ?? false,
      homeAdvantageValue:
          (json['home_advantage_value'] as num?)?.toDouble() ?? 0,
      warnings: List<String>.from(json['warnings'] as List<dynamic>? ?? []),
    );
  }
}

class PredictionResult {
  final String homeTeam;
  final String awayTeam;
  final double homePower;
  final double awayPower;
  final TeamBreakdown homeBreakdown;
  final TeamBreakdown awayBreakdown;
  final double homeXg;
  final double awayXg;
  final Probabilities1X2 probabilities;
  final OutcomeExplanations outcomeExplanations;
  final List<ScoreProbability> topScores;
  final ScoreCoverage scoreCoverage;
  final String matchSummary;
  final String h2hSummary;
  final MatchContextInfo? matchContext;
  final ScorelineDecision? scorelineDecision;
  final MatchContextDiagnostics? matchContextDiagnostics;

  const PredictionResult({
    required this.homeTeam,
    required this.awayTeam,
    required this.homePower,
    required this.awayPower,
    required this.homeBreakdown,
    required this.awayBreakdown,
    required this.homeXg,
    required this.awayXg,
    required this.probabilities,
    required this.outcomeExplanations,
    required this.topScores,
    required this.scoreCoverage,
    this.matchSummary = '',
    this.h2hSummary = '',
    this.matchContext,
    this.scorelineDecision,
    this.matchContextDiagnostics,
  });

  factory PredictionResult.fromJson(Map<String, dynamic> json) {
    return PredictionResult(
      homeTeam: json['home_team'] as String,
      awayTeam: json['away_team'] as String,
      homePower: (json['home_power'] as num).toDouble(),
      awayPower: (json['away_power'] as num).toDouble(),
      homeBreakdown: TeamBreakdown.fromJson(
        json['home_breakdown'] as Map<String, dynamic>,
      ),
      awayBreakdown: TeamBreakdown.fromJson(
        json['away_breakdown'] as Map<String, dynamic>,
      ),
      homeXg: (json['home_xg'] as num).toDouble(),
      awayXg: (json['away_xg'] as num).toDouble(),
      probabilities: Probabilities1X2.fromJson(
        json['probabilities_1x2'] as Map<String, dynamic>,
      ),
      outcomeExplanations: OutcomeExplanations.fromJson(
        json['outcome_explanations'] as Map<String, dynamic>,
      ),
      topScores: (json['top_scores'] as List<dynamic>)
          .map((e) => ScoreProbability.fromJson(e as Map<String, dynamic>))
          .toList(),
      scoreCoverage: ScoreCoverage.fromJson(
        json['score_coverage'] as Map<String, dynamic>,
      ),
      matchSummary: json['match_summary'] as String? ?? '',
      h2hSummary: json['h2h_summary'] as String? ?? '',
      matchContext: json['match_context'] != null
          ? MatchContextInfo.fromJson(
              json['match_context'] as Map<String, dynamic>,
            )
          : null,
      scorelineDecision: json['scoreline_decision'] != null
          ? ScorelineDecision.fromJson(
              json['scoreline_decision'] as Map<String, dynamic>,
            )
          : null,
      matchContextDiagnostics: json['match_context_diagnostics'] != null
          ? MatchContextDiagnostics.fromJson(
              json['match_context_diagnostics'] as Map<String, dynamic>,
            )
          : null,
    );
  }
}

class GroupStanding {
  final String group;
  final String team;
  final double avgPoints;
  final double top2Probability;
  final double winGroupProbability;

  const GroupStanding({
    required this.group,
    required this.team,
    required this.avgPoints,
    required this.top2Probability,
    required this.winGroupProbability,
  });

  factory GroupStanding.fromJson(Map<String, dynamic> json) {
    return GroupStanding(
      group: json['group'] as String,
      team: json['team'] as String,
      avgPoints: (json['avg_points'] as num).toDouble(),
      top2Probability: (json['top2_probability'] as num).toDouble(),
      winGroupProbability: (json['win_group_probability'] as num).toDouble(),
    );
  }
}

class ChampionOdds {
  final String team;
  final double probability;

  const ChampionOdds({required this.team, required this.probability});

  factory ChampionOdds.fromJson(Map<String, dynamic> json) {
    return ChampionOdds(
      team: json['team'] as String,
      probability: (json['probability'] as num).toDouble(),
    );
  }
}

class PredictionSettings {
  final double rho;
  final double avgGoals;
  final double homeAdvantage;
  final double alpha;
  final int altitude;
  final bool starAbsent;
  final bool awayStarAbsent;
  final bool neutralGround;
  final bool useLiveStats;
  final String apiBaseUrl;

  const PredictionSettings({
    this.rho = -0.15,
    this.avgGoals = 2.6,
    this.homeAdvantage = 0,
    this.alpha = 0.0,
    this.altitude = 0,
    this.starAbsent = false,
    this.awayStarAbsent = false,
    this.neutralGround = true,
    this.useLiveStats = false,
    this.apiBaseUrl = productionApiUrl,
  });

  PredictionSettings copyWith({
    double? rho,
    double? avgGoals,
    double? homeAdvantage,
    double? alpha,
    int? altitude,
    bool? starAbsent,
    bool? awayStarAbsent,
    bool? neutralGround,
    bool? useLiveStats,
    String? apiBaseUrl,
  }) {
    return PredictionSettings(
      rho: rho ?? this.rho,
      avgGoals: avgGoals ?? this.avgGoals,
      homeAdvantage: homeAdvantage ?? this.homeAdvantage,
      alpha: alpha ?? this.alpha,
      altitude: altitude ?? this.altitude,
      starAbsent: starAbsent ?? this.starAbsent,
      awayStarAbsent: awayStarAbsent ?? this.awayStarAbsent,
      neutralGround: neutralGround ?? this.neutralGround,
      useLiveStats: useLiveStats ?? this.useLiveStats,
      apiBaseUrl: apiBaseUrl ?? this.apiBaseUrl,
    );
  }
}
