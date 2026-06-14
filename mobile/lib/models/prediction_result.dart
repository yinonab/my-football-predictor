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
    this.avgGoals = 3.0,
    this.homeAdvantage = 0,
    this.alpha = 0.0,
    this.altitude = 0,
    this.starAbsent = false,
    this.awayStarAbsent = false,
    this.neutralGround = true,
    this.useLiveStats = false,
    this.apiBaseUrl = 'http://10.0.2.2:8000',
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
