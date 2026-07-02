import 'package:flutter_test/flutter_test.dart';

import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/models/venue_mode.dart';
import 'package:football_predictor/models/xg_model_variant.dart';

void main() {
  test('default xg model variant is NR3+FCC', () {
    const settings = PredictionSettings();
    expect(settings.xgModelVariant, XgModelVariant.nr3Fcc);
  });

  test('buildPredictRequestBody sends xg_model_variant', () {
    final nr3 = buildPredictRequestBody(
      homeTeam: 'France',
      awayTeam: 'Haiti',
      venueMode: VenueMode.neutral,
      rho: -0.15,
      avgGoals: 2.6,
      homeAdvantage: 0,
      alpha: 0,
      altitude: 0,
      starAbsent: false,
      awayStarAbsent: false,
      useLiveStats: false,
    );
    expect(nr3['xg_model_variant'], 'nr3_fcc');

    final matchup = buildPredictRequestBody(
      homeTeam: 'France',
      awayTeam: 'Haiti',
      venueMode: VenueMode.neutral,
      rho: -0.15,
      avgGoals: 2.6,
      homeAdvantage: 0,
      alpha: 0,
      altitude: 0,
      starAbsent: false,
      awayStarAbsent: false,
      useLiveStats: false,
      xgModelVariant: 'matchup_relative_v1',
    );
    expect(matchup['xg_model_variant'], 'matchup_relative_v1');
  });

  test('ModelDiagnostics parses active model badge fields', () {
    final diag = ModelDiagnostics.fromJson({
      'model_version': 'matchup_relative_xg_v1',
      'active_xg_source': 'matchup_relative_v1',
      'model_variant': 'matchup_relative_v1',
      'home_xg_source': 'matchup_relative_v1',
      'away_xg_source': 'matchup_relative_v1',
    });
    expect(diag.activeModelBadgeLabelResolved, 'מודל פעיל: Matchup Relative — ניסיוני');
  });

  test('ModelDiagnostics defaults to NR3 badge when variant missing', () {
    const diag = ModelDiagnostics(modelVersion: 'v2.3.0-nr3-fcc-served');
    expect(diag.activeModelBadgeLabelResolved, 'מודל פעיל: NR3+FCC');
  });
}
