/// Phase 4P — venue_mode contract (maps to backend Phase 4O).
enum VenueMode {
  neutral,
  firstTeamHome,
  secondTeamHome,
  hostCountryAuto,
}

extension VenueModeApi on VenueMode {
  String get apiValue {
    switch (this) {
      case VenueMode.neutral:
        return 'neutral';
      case VenueMode.firstTeamHome:
        return 'first_team_home';
      case VenueMode.secondTeamHome:
        return 'second_team_home';
      case VenueMode.hostCountryAuto:
        return 'host_country_auto';
    }
  }

  bool get isNeutralGround => this == VenueMode.neutral;

  static VenueMode? fromApi(String? value) {
    switch (value) {
      case 'neutral':
        return VenueMode.neutral;
      case 'first_team_home':
        return VenueMode.firstTeamHome;
      case 'second_team_home':
        return VenueMode.secondTeamHome;
      case 'host_country_auto':
        return VenueMode.hostCountryAuto;
      default:
        return null;
    }
  }
}

VenueMode venueModeFromNeutralGround(bool neutralGround) {
  return neutralGround ? VenueMode.neutral : VenueMode.firstTeamHome;
}

Map<String, dynamic> buildPredictRequestBody({
  required String homeTeam,
  required String awayTeam,
  required VenueMode venueMode,
  required double rho,
  required double avgGoals,
  required double homeAdvantage,
  required double alpha,
  required int altitude,
  required bool starAbsent,
  required bool awayStarAbsent,
  required bool useLiveStats,
  bool oddsAffectPrediction = false,
  bool fusionBlowoutEnabled = false,
  bool useMatchContext = true,
  bool autoStadiumAltitude = true,
  bool includeDiagnostics = true,
  String? venueCity,
  String? matchDate,
  int topN = 3,
}) {
  final body = <String, dynamic>{
    'home_team': homeTeam,
    'away_team': awayTeam,
    'venue_mode': venueMode.apiValue,
    'neutral_ground': venueMode.isNeutralGround,
    'rho': rho,
    'avg_goals': avgGoals,
    'home_advantage': homeAdvantage,
    'alpha': alpha,
    'altitude': altitude,
    'star_absent': starAbsent,
    'away_star_absent': awayStarAbsent,
    'use_live_stats': useLiveStats,
    'use_match_context': useMatchContext,
    'odds_affect_prediction': oddsAffectPrediction,
    'fusion_blowout_enabled': fusionBlowoutEnabled,
    'auto_stadium_altitude': autoStadiumAltitude,
    'include_diagnostics': includeDiagnostics,
    'top_n': topN,
  };
  if (venueCity != null && venueCity.trim().isNotEmpty) {
    body['venue_city'] = venueCity.trim();
  }
  if (matchDate != null && matchDate.trim().isNotEmpty) {
    body['match_date'] = matchDate.trim();
  }
  return body;
}
