enum GoalCapabilityLevel {
  low,
  medium,
  significant,
  mediumHigh,
  high,
}

GoalCapabilityLevel? goalCapabilityLevelFromString(String? raw) {
  switch (raw?.toUpperCase()) {
    case 'LOW':
      return GoalCapabilityLevel.low;
    case 'MEDIUM':
      return GoalCapabilityLevel.medium;
    case 'SIGNIFICANT':
      return GoalCapabilityLevel.significant;
    case 'MEDIUM_HIGH':
      return GoalCapabilityLevel.mediumHigh;
    case 'HIGH':
      return GoalCapabilityLevel.high;
    default:
      return null;
  }
}

String goalCapabilityLevelHebrew(GoalCapabilityLevel level) {
  switch (level) {
    case GoalCapabilityLevel.low:
      return 'נמוכה';
    case GoalCapabilityLevel.medium:
      return 'בינונית';
    case GoalCapabilityLevel.significant:
      return 'משמעותית';
    case GoalCapabilityLevel.mediumHigh:
      return 'בינונית-גבוהה';
    case GoalCapabilityLevel.high:
      return 'גבוהה';
  }
}

class MatchupGoalCapabilitySummary {
  final String title;
  final String shortText;
  final String cleanSheetText;
  final String underdogText;
  final String favoriteText;

  const MatchupGoalCapabilitySummary({
    required this.title,
    required this.shortText,
    this.cleanSheetText = '',
    this.underdogText = '',
    this.favoriteText = '',
  });

  factory MatchupGoalCapabilitySummary.fromJson(Map<String, dynamic> json) {
    return MatchupGoalCapabilitySummary(
      title: json['title'] as String? ?? 'יכולת הבקעה לפי מפגש',
      shortText: json['short_text'] as String? ?? '',
      cleanSheetText: json['clean_sheet_text'] as String? ?? '',
      underdogText: json['underdog_text'] as String? ?? '',
      favoriteText: json['favorite_text'] as String? ?? '',
    );
  }
}

class MatchupGoalCapabilityProbabilities {
  final double homeScoresProbability;
  final double awayScoresProbability;
  final double favoriteScoresProbability;
  final double underdogScoresProbability;
  final double favoriteScores2PlusProbability;
  final double favoriteScores3PlusProbability;
  final double bttsProbability;

  const MatchupGoalCapabilityProbabilities({
    required this.homeScoresProbability,
    required this.awayScoresProbability,
    required this.favoriteScoresProbability,
    required this.underdogScoresProbability,
    required this.favoriteScores2PlusProbability,
    required this.favoriteScores3PlusProbability,
    required this.bttsProbability,
  });

  factory MatchupGoalCapabilityProbabilities.fromJson(
    Map<String, dynamic> json,
  ) {
    double read(String key) => (json[key] as num?)?.toDouble() ?? 0.0;
    return MatchupGoalCapabilityProbabilities(
      homeScoresProbability: read('home_scores_probability'),
      awayScoresProbability: read('away_scores_probability'),
      favoriteScoresProbability: read('favorite_scores_probability'),
      underdogScoresProbability: read('underdog_scores_probability'),
      favoriteScores2PlusProbability: read('favorite_scores_2_plus_probability'),
      favoriteScores3PlusProbability: read('favorite_scores_3_plus_probability'),
      bttsProbability: read('btts_probability'),
    );
  }
}

class MatchupGoalCapabilityInputs {
  final double servedHomeXg;
  final double servedAwayXg;
  final double? maherReferenceHomeXg;
  final double? maherReferenceAwayXg;
  final double? homeAttackRating;
  final double? homeDefenseRating;
  final double? awayAttackRating;
  final double? awayDefenseRating;
  final double? homeGfPerGame;
  final double? homeGaPerGame;
  final double? awayGfPerGame;
  final double? awayGaPerGame;
  final double? powerGap;

  const MatchupGoalCapabilityInputs({
    required this.servedHomeXg,
    required this.servedAwayXg,
    this.maherReferenceHomeXg,
    this.maherReferenceAwayXg,
    this.homeAttackRating,
    this.homeDefenseRating,
    this.awayAttackRating,
    this.awayDefenseRating,
    this.homeGfPerGame,
    this.homeGaPerGame,
    this.awayGfPerGame,
    this.awayGaPerGame,
    this.powerGap,
  });

  factory MatchupGoalCapabilityInputs.fromJson(Map<String, dynamic> json) {
    double? opt(String key) => (json[key] as num?)?.toDouble();
    return MatchupGoalCapabilityInputs(
      servedHomeXg: (json['served_home_xg'] as num?)?.toDouble() ?? 0.0,
      servedAwayXg: (json['served_away_xg'] as num?)?.toDouble() ?? 0.0,
      maherReferenceHomeXg: opt('maher_reference_home_xg'),
      maherReferenceAwayXg: opt('maher_reference_away_xg'),
      homeAttackRating: opt('home_attack_rating'),
      homeDefenseRating: opt('home_defense_rating'),
      awayAttackRating: opt('away_attack_rating'),
      awayDefenseRating: opt('away_defense_rating'),
      homeGfPerGame: opt('home_gf_per_game'),
      homeGaPerGame: opt('home_ga_per_game'),
      awayGfPerGame: opt('away_gf_per_game'),
      awayGaPerGame: opt('away_ga_per_game'),
      powerGap: opt('power_gap'),
    );
  }
}

class MatchupGoalCapability {
  final String activeModel;
  final String homeTeam;
  final String awayTeam;
  final String favoriteTeam;
  final String underdogTeam;
  final GoalCapabilityLevel? homeGoalCapability;
  final GoalCapabilityLevel? awayGoalCapability;
  final GoalCapabilityLevel? favoriteGoalCapability;
  final GoalCapabilityLevel? underdogGoalCapability;
  final GoalCapabilityLevel? favoriteMultiGoalCapability;
  final GoalCapabilityLevel? favoriteCleanSheetReliability;
  final GoalCapabilityLevel? cleanSheetRisk;
  final GoalCapabilityLevel? bttsLikelihood;
  final MatchupGoalCapabilityProbabilities probabilities;
  final MatchupGoalCapabilityInputs matchupInputs;
  final List<String> reasonCodes;
  final MatchupGoalCapabilitySummary summary;

  const MatchupGoalCapability({
    required this.activeModel,
    required this.homeTeam,
    required this.awayTeam,
    required this.favoriteTeam,
    required this.underdogTeam,
    this.homeGoalCapability,
    this.awayGoalCapability,
    this.favoriteGoalCapability,
    this.underdogGoalCapability,
    this.favoriteMultiGoalCapability,
    this.favoriteCleanSheetReliability,
    this.cleanSheetRisk,
    this.bttsLikelihood,
    required this.probabilities,
    required this.matchupInputs,
    this.reasonCodes = const [],
    required this.summary,
  });

  factory MatchupGoalCapability.fromJson(Map<String, dynamic> json) {
    return MatchupGoalCapability(
      activeModel: json['active_model'] as String? ?? '',
      homeTeam: json['home_team'] as String? ?? '',
      awayTeam: json['away_team'] as String? ?? '',
      favoriteTeam: json['favorite_team'] as String? ?? '',
      underdogTeam: json['underdog_team'] as String? ?? '',
      homeGoalCapability:
          goalCapabilityLevelFromString(json['home_goal_capability'] as String?),
      awayGoalCapability:
          goalCapabilityLevelFromString(json['away_goal_capability'] as String?),
      favoriteGoalCapability: goalCapabilityLevelFromString(
        json['favorite_goal_capability'] as String?,
      ),
      underdogGoalCapability: goalCapabilityLevelFromString(
        json['underdog_goal_capability'] as String?,
      ),
      favoriteMultiGoalCapability: goalCapabilityLevelFromString(
        json['favorite_multi_goal_capability'] as String?,
      ),
      favoriteCleanSheetReliability: goalCapabilityLevelFromString(
        json['favorite_clean_sheet_reliability'] as String?,
      ),
      cleanSheetRisk:
          goalCapabilityLevelFromString(json['clean_sheet_risk'] as String?),
      bttsLikelihood:
          goalCapabilityLevelFromString(json['btts_likelihood'] as String?),
      probabilities: MatchupGoalCapabilityProbabilities.fromJson(
        json['probabilities'] as Map<String, dynamic>? ?? {},
      ),
      matchupInputs: MatchupGoalCapabilityInputs.fromJson(
        json['matchup_inputs'] as Map<String, dynamic>? ?? {},
      ),
      reasonCodes: List<String>.from(json['reason_codes'] as List<dynamic>? ?? []),
      summary: MatchupGoalCapabilitySummary.fromJson(
        json['summary'] as Map<String, dynamic>? ?? {},
      ),
    );
  }
}
