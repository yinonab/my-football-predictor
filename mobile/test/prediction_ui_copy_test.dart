import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/utils/prediction_ui_copy.dart';

void main() {
  test('shouldShowRestDays hides unreliable huge values', () {
    expect(
      shouldShowRestDays(
        const MatchContextDiagnostics(fixtureSourceAvailable: false),
        const MatchContextInfo(homeRestDays: 713, awayRestDays: 379),
      ),
      isFalse,
    );
  });

  test('hasLiveFixtureUnavailableWarning maps suspended code', () {
    final result = PredictionResult(
      homeTeam: 'Canada',
      awayTeam: 'Qatar',
      homePower: 1,
      awayPower: 1,
      homeBreakdown: const TeamBreakdown(
        name: 'Canada',
        powerScore: 1,
        elo: 1,
        breakdown: '',
      ),
      awayBreakdown: const TeamBreakdown(
        name: 'Qatar',
        powerScore: 1,
        elo: 1,
        breakdown: '',
      ),
      homeXg: 1.6,
      awayXg: 1.0,
      probabilities: const Probabilities1X2(homeWin: 50, draw: 25, awayWin: 25),
      outcomeExplanations: const OutcomeExplanations(
        homeWin: '',
        draw: '',
        awayWin: '',
      ),
      topScores: const [],
      scoreCoverage: const ScoreCoverage(
        targetPercent: 50,
        achievedPercent: 50,
        scores: [],
      ),
      matchContextDiagnostics: const MatchContextDiagnostics(
        warnings: ['API_FOOTBALL_ACCOUNT_SUSPENDED'],
      ),
    );

    expect(hasLiveFixtureUnavailableWarning(result), isTrue);
  });
}
