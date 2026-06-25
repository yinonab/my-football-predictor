import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/models/venue_mode.dart';
import 'package:football_predictor/utils/environment_ui_copy.dart';

void main() {
  test('buildPredictRequestBody includes venue_city and match_date when set', () {
    final body = buildPredictRequestBody(
      homeTeam: 'A',
      awayTeam: 'B',
      venueMode: VenueMode.neutral,
      rho: -0.15,
      avgGoals: 2.6,
      homeAdvantage: 0,
      alpha: 0,
      altitude: 0,
      starAbsent: false,
      awayStarAbsent: false,
      useLiveStats: false,
      venueCity: 'Mexico City',
      matchDate: '2026-06-15',
    );

    expect(body['venue_city'], 'Mexico City');
    expect(body['match_date'], '2026-06-15');
  });

  test('buildPredictRequestBody omits venue when not set', () {
    final body = buildPredictRequestBody(
      homeTeam: 'A',
      awayTeam: 'B',
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

    expect(body.containsKey('venue_city'), isFalse);
    expect(body.containsKey('match_date'), isFalse);
  });

  test('buildPredictRequestBody sends fusion and market flags', () {
    final body = buildPredictRequestBody(
      homeTeam: 'A',
      awayTeam: 'B',
      venueMode: VenueMode.neutral,
      rho: -0.15,
      avgGoals: 2.6,
      homeAdvantage: 0,
      alpha: 0,
      altitude: 0,
      starAbsent: false,
      awayStarAbsent: false,
      useLiveStats: false,
      oddsAffectPrediction: true,
      fusionBlowoutEnabled: true,
      useMatchContext: false,
      autoStadiumAltitude: false,
    );

    expect(body['odds_affect_prediction'], isTrue);
    expect(body['fusion_blowout_enabled'], isTrue);
    expect(body['use_match_context'], isFalse);
    expect(body['auto_stadium_altitude'], isFalse);
  });

  test('environment summary includes stadium altitude and provider', () {
    final result = PredictionResult.fromJson({
      'home_team': 'A',
      'away_team': 'B',
      'home_power': 700,
      'away_power': 680,
      'home_breakdown': {
        'name': 'A',
        'power_score': 700,
        'elo': 1400,
        'breakdown': '',
      },
      'away_breakdown': {
        'name': 'B',
        'power_score': 680,
        'elo': 1380,
        'breakdown': '',
      },
      'home_xg': 1.4,
      'away_xg': 1.2,
      'probabilities_1x2': {'home_win': 40, 'draw': 30, 'away_win': 30},
      'outcome_explanations': {
        'home_win': 'h',
        'draw': 'd',
        'away_win': 'a',
      },
      'top_scores': [
        {'score': '1-1', 'probability': 12, 'explanation': ''},
      ],
      'score_coverage': {
        'target_percent': 50,
        'achieved_percent': 50,
        'scores': ['1-1'],
      },
      'environment_diagnostics': {
        'venue_stadium': 'Estadio Azteca',
        'venue_city': 'Mexico City',
        'venue_altitude_m': 2240,
        'altitude_bucket': 'very_high',
        'weather_source': 'open-meteo',
        'weather_adjustment_mode': 'none',
        'automatic_altitude_adjustment_mode': 'diagnostic_only',
      },
      'recent_form_provider_diagnostics': {
        'primary_provider': 'sofascore_recent_form',
        'source_mix': {'sofascore_recent_form': 8},
        'confidence_bucket': 'high',
      },
    });

    final lines = buildEnvironmentSummaryLines(result);
    expect(lines.any((l) => l.contains('Estadio Azteca')), isTrue);
    expect(lines.any((l) => l.contains('2240')), isTrue);
    expect(lines.any((l) => l.contains('Sofascore')), isTrue);
  });
}
