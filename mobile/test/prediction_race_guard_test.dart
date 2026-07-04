import 'package:flutter_test/flutter_test.dart';

import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/models/venue_mode.dart';
import 'package:football_predictor/utils/prediction_request_guard.dart';

void main() {
  test('samePredictSettings detects venue mode change', () {
    const base = PredictionSettings();
    const alt = PredictionSettings(venueMode: VenueMode.firstTeamHome);
    expect(samePredictSettings(base, base), isTrue);
    expect(samePredictSettings(base, alt), isFalse);
  });

  test('PredictRequestIdentity holds captured teams', () {
    const identity = PredictRequestIdentity(
      homeTeam: 'France',
      awayTeam: 'Paraguay',
      settings: PredictionSettings(),
    );
    expect(identity.homeTeam, 'France');
    expect(identity.awayTeam, 'Paraguay');
  });
}
