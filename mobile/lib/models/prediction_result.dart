import '../config/api_config.dart';
import 'market_diagnostics.dart';
import 'venue_mode.dart';

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
  final Map<String, dynamic> representativeSelection;

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
    this.representativeSelection = const {},
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
      representativeSelection: Map<String, dynamic>.from(
        json['representative_selection'] as Map<String, dynamic>? ??
            json['favorite_goal_volume_uplift'] as Map<String, dynamic>? ??
            {},
      ),
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

class EnvironmentDiagnostics {
  final String? venueCity;
  final String? venueCountry;
  final String? venueStadium;
  final double? venueLatitude;
  final double? venueLongitude;
  final int? venueAltitudeM;
  final String altitudeBucket;
  final String altitudeSource;
  final int? requestAltitudeM;
  final bool manualAltitudeApplied;
  final int activeAltitudeThresholdM;
  final String automaticAltitudeAdjustmentMode;
  final String weatherSource;
  final String? weatherFetchedAt;
  final double? temperatureC;
  final double? precipitationMm;
  final String? weatherSummary;
  final String weatherAdjustmentMode;
  final double activeWeatherXgDelta;
  final double shadowWeatherXgDelta;
  final double? shadowAltitudePowerMultiplier;
  final List<String> environmentNotes;
  final List<String> environmentWarnings;

  const EnvironmentDiagnostics({
    this.venueCity,
    this.venueCountry,
    this.venueStadium,
    this.venueLatitude,
    this.venueLongitude,
    this.venueAltitudeM,
    this.altitudeBucket = 'unknown',
    this.altitudeSource = 'unknown',
    this.requestAltitudeM,
    this.manualAltitudeApplied = false,
    this.activeAltitudeThresholdM = 1200,
    this.automaticAltitudeAdjustmentMode = 'diagnostic_only',
    this.weatherSource = 'not_requested',
    this.weatherFetchedAt,
    this.temperatureC,
    this.precipitationMm,
    this.weatherSummary,
    this.weatherAdjustmentMode = 'none',
    this.activeWeatherXgDelta = 0,
    this.shadowWeatherXgDelta = 0,
    this.shadowAltitudePowerMultiplier,
    this.environmentNotes = const [],
    this.environmentWarnings = const [],
  });

  factory EnvironmentDiagnostics.fromJson(Map<String, dynamic> json) {
    return EnvironmentDiagnostics(
      venueCity: json['venue_city'] as String?,
      venueCountry: json['venue_country'] as String?,
      venueStadium: json['venue_stadium'] as String?,
      venueLatitude: (json['venue_latitude'] as num?)?.toDouble(),
      venueLongitude: (json['venue_longitude'] as num?)?.toDouble(),
      venueAltitudeM: json['venue_altitude_m'] as int?,
      altitudeBucket: json['altitude_bucket'] as String? ?? 'unknown',
      altitudeSource: json['altitude_source'] as String? ?? 'unknown',
      requestAltitudeM: json['request_altitude_m'] as int?,
      manualAltitudeApplied: json['manual_altitude_applied'] as bool? ?? false,
      activeAltitudeThresholdM:
          json['active_altitude_threshold_m'] as int? ?? 1200,
      automaticAltitudeAdjustmentMode:
          json['automatic_altitude_adjustment_mode'] as String? ??
          'diagnostic_only',
      weatherSource: json['weather_source'] as String? ?? 'not_requested',
      weatherFetchedAt: json['weather_fetched_at'] as String?,
      temperatureC: (json['temperature_c'] as num?)?.toDouble(),
      precipitationMm: (json['precipitation_mm'] as num?)?.toDouble(),
      weatherSummary: json['weather_summary'] as String?,
      weatherAdjustmentMode:
          json['weather_adjustment_mode'] as String? ?? 'none',
      activeWeatherXgDelta:
          (json['active_weather_xg_delta'] as num?)?.toDouble() ?? 0,
      shadowWeatherXgDelta:
          (json['shadow_weather_xg_delta'] as num?)?.toDouble() ?? 0,
      shadowAltitudePowerMultiplier:
          (json['shadow_altitude_power_multiplier'] as num?)?.toDouble(),
      environmentNotes: List<String>.from(
        json['environment_notes'] as List<dynamic>? ?? [],
      ),
      environmentWarnings: List<String>.from(
        json['environment_warnings'] as List<dynamic>? ?? [],
      ),
    );
  }
}

class RecentFormProviderDiagnostics {
  final Map<String, int> sourceMix;
  final String primaryProvider;
  final String? cacheLastUpdatedUtc;
  final Map<String, Map<String, dynamic>> teamsWithProviderIds;
  final String confidenceBucket;
  final List<String> providerNotes;

  const RecentFormProviderDiagnostics({
    this.sourceMix = const {},
    this.primaryProvider = 'unavailable',
    this.cacheLastUpdatedUtc,
    this.teamsWithProviderIds = const {},
    this.confidenceBucket = 'unknown',
    this.providerNotes = const [],
  });

  factory RecentFormProviderDiagnostics.fromJson(Map<String, dynamic> json) {
    final rawMix = json['source_mix'] as Map<String, dynamic>? ?? {};
    return RecentFormProviderDiagnostics(
      sourceMix: rawMix.map(
        (key, value) => MapEntry(key, (value as num).toInt()),
      ),
      primaryProvider: json['primary_provider'] as String? ?? 'unavailable',
      cacheLastUpdatedUtc: json['cache_last_updated_utc'] as String?,
      teamsWithProviderIds:
          (json['teams_with_provider_ids'] as Map<String, dynamic>? ?? {}).map(
        (key, value) => MapEntry(
          key,
          Map<String, dynamic>.from(value as Map<String, dynamic>),
        ),
      ),
      confidenceBucket: json['confidence_bucket'] as String? ?? 'unknown',
      providerNotes: List<String>.from(
        json['provider_notes'] as List<dynamic>? ?? [],
      ),
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
  final String? venueMode;
  final String? homeAdvantageTeam;
  final bool neutralGroundRequested;
  final bool hostCountryMatch;
  final String? hostAdvantageCandidateTeam;
  final bool hostAdvantageApplied;
  final double homeAdvantageValue;
  final double homeAdvantagePowerDelta;
  final List<String> warnings;

  const MatchContextDiagnostics({
    this.fixtureStatus = 'unknown',
    this.predictionValid = true,
    this.predictionMode = 'unknown',
    this.actualScore,
    this.fixtureSourceAvailable = false,
    this.venueContextAvailable = false,
    this.venueMode,
    this.homeAdvantageTeam,
    this.neutralGroundRequested = true,
    this.hostCountryMatch = false,
    this.hostAdvantageCandidateTeam,
    this.hostAdvantageApplied = false,
    this.homeAdvantageValue = 0,
    this.homeAdvantagePowerDelta = 0,
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
      venueMode: json['venue_mode'] as String?,
      homeAdvantageTeam: json['home_advantage_team'] as String?,
      neutralGroundRequested:
          json['neutral_ground_requested'] as bool? ?? true,
      hostCountryMatch: json['host_country_match'] as bool? ?? false,
      hostAdvantageCandidateTeam:
          json['host_advantage_candidate_team'] as String?,
      hostAdvantageApplied:
          json['host_advantage_applied'] as bool? ??
          json['home_advantage_applied'] as bool? ??
          false,
      homeAdvantageValue:
          (json['home_advantage_value'] as num?)?.toDouble() ?? 0,
      homeAdvantagePowerDelta:
          (json['home_advantage_power_delta'] as num?)?.toDouble() ?? 0,
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
  final double? baseHomeXg;
  final double? baseAwayXg;
  final bool blowoutAdjustmentApplied;
  final double? adjustedHomeXg;
  final double? adjustedAwayXg;
  final Probabilities1X2 probabilities;
  final OutcomeExplanations outcomeExplanations;
  final List<ScoreProbability> topScores;
  final ScoreCoverage scoreCoverage;
  final String matchSummary;
  final String h2hSummary;
  final MatchContextInfo? matchContext;
  final ScorelineDecision? scorelineDecision;
  final MatchContextDiagnostics? matchContextDiagnostics;
  final EnvironmentDiagnostics? environmentDiagnostics;
  final RecentFormProviderDiagnostics? recentFormProviderDiagnostics;
  final ProbabilityDiagnostics? probabilityDiagnostics;
  final MarketDiagnosticsPayload? marketDiagnostics;

  bool get oddsAffectPrediction =>
      probabilityDiagnostics?.oddsAffectPrediction ?? false;

  bool get oddsBlendApplied =>
      probabilityDiagnostics?.oddsBlendApplied ?? false;

  const PredictionResult({
    required this.homeTeam,
    required this.awayTeam,
    required this.homePower,
    required this.awayPower,
    required this.homeBreakdown,
    required this.awayBreakdown,
    required this.homeXg,
    required this.awayXg,
    this.baseHomeXg,
    this.baseAwayXg,
    this.blowoutAdjustmentApplied = false,
    this.adjustedHomeXg,
    this.adjustedAwayXg,
    required this.probabilities,
    required this.outcomeExplanations,
    required this.topScores,
    required this.scoreCoverage,
    this.matchSummary = '',
    this.h2hSummary = '',
    this.matchContext,
    this.scorelineDecision,
    this.matchContextDiagnostics,
    this.environmentDiagnostics,
    this.recentFormProviderDiagnostics,
    this.probabilityDiagnostics,
    this.marketDiagnostics,
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
      baseHomeXg: (json['base_home_xg'] as num?)?.toDouble(),
      baseAwayXg: (json['base_away_xg'] as num?)?.toDouble(),
      blowoutAdjustmentApplied:
          json['blowout_adjustment_applied'] as bool? ?? false,
      adjustedHomeXg: (json['adjusted_home_xg'] as num?)?.toDouble(),
      adjustedAwayXg: (json['adjusted_away_xg'] as num?)?.toDouble(),
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
      environmentDiagnostics: json['environment_diagnostics'] != null
          ? EnvironmentDiagnostics.fromJson(
              json['environment_diagnostics'] as Map<String, dynamic>,
            )
          : null,
      recentFormProviderDiagnostics:
          json['recent_form_provider_diagnostics'] != null
              ? RecentFormProviderDiagnostics.fromJson(
                  json['recent_form_provider_diagnostics']
                      as Map<String, dynamic>,
                )
              : null,
      probabilityDiagnostics: json['probability_diagnostics'] != null
          ? ProbabilityDiagnostics.fromJson(
              json['probability_diagnostics'] as Map<String, dynamic>,
            )
          : null,
      marketDiagnostics: json['market_diagnostics'] != null
          ? MarketDiagnosticsPayload.fromJson(
              json['market_diagnostics'] as Map<String, dynamic>,
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
  final VenueMode venueMode;
  final bool useLiveStats;
  final String apiBaseUrl;
  final String? venueCity;
  final String? matchDate;

  const PredictionSettings({
    this.rho = -0.15,
    this.avgGoals = 2.6,
    this.homeAdvantage = 0,
    this.alpha = 0.0,
    this.altitude = 0,
    this.starAbsent = false,
    this.awayStarAbsent = false,
    this.venueMode = VenueMode.neutral,
    this.useLiveStats = false,
    this.apiBaseUrl = productionApiUrl,
    this.venueCity,
    this.matchDate,
  });

  bool get neutralGround => venueMode.isNeutralGround;

  PredictionSettings copyWith({
    double? rho,
    double? avgGoals,
    double? homeAdvantage,
    double? alpha,
    int? altitude,
    bool? starAbsent,
    bool? awayStarAbsent,
    VenueMode? venueMode,
    bool? neutralGround,
    bool? useLiveStats,
    String? apiBaseUrl,
    String? venueCity,
    String? matchDate,
    bool clearVenueCity = false,
    bool clearMatchDate = false,
  }) {
    VenueMode resolved = venueMode ?? this.venueMode;
    if (neutralGround != null) {
      resolved = venueModeFromNeutralGround(neutralGround);
    }
    return PredictionSettings(
      rho: rho ?? this.rho,
      avgGoals: avgGoals ?? this.avgGoals,
      homeAdvantage: homeAdvantage ?? this.homeAdvantage,
      alpha: alpha ?? this.alpha,
      altitude: altitude ?? this.altitude,
      starAbsent: starAbsent ?? this.starAbsent,
      awayStarAbsent: awayStarAbsent ?? this.awayStarAbsent,
      venueMode: resolved,
      useLiveStats: useLiveStats ?? this.useLiveStats,
      apiBaseUrl: apiBaseUrl ?? this.apiBaseUrl,
      venueCity: clearVenueCity ? null : (venueCity ?? this.venueCity),
      matchDate: clearMatchDate ? null : (matchDate ?? this.matchDate),
    );
  }
}
