import '../models/prediction_result.dart';

/// Snapshot of teams + settings sent with a single predict request.
class PredictRequestIdentity {
  const PredictRequestIdentity({
    required this.homeTeam,
    required this.awayTeam,
    required this.settings,
  });

  final String homeTeam;
  final String awayTeam;
  final PredictionSettings settings;
}

bool samePredictSettings(PredictionSettings a, PredictionSettings b) {
  return a.rho == b.rho &&
      a.avgGoals == b.avgGoals &&
      a.homeAdvantage == b.homeAdvantage &&
      a.alpha == b.alpha &&
      a.altitude == b.altitude &&
      a.starAbsent == b.starAbsent &&
      a.awayStarAbsent == b.awayStarAbsent &&
      a.venueMode == b.venueMode &&
      a.useLiveStats == b.useLiveStats &&
      a.oddsAffectPrediction == b.oddsAffectPrediction &&
      a.fusionBlowoutEnabled == b.fusionBlowoutEnabled &&
      a.useMatchContext == b.useMatchContext &&
      a.autoStadiumAltitude == b.autoStadiumAltitude &&
      a.venueCity == b.venueCity &&
      a.matchDate == b.matchDate;
}
