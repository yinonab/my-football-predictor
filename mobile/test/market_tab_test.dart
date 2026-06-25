import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/market_tab_view_model.dart';
import 'package:football_predictor/models/prediction_result.dart';

void main() {
  PredictionResult baseResult(Map<String, dynamic> extra) {
    return PredictionResult.fromJson({
      'home_team': 'Brazil (ברזיל)',
      'away_team': 'France (צרפת)',
      'home_power': 720,
      'away_power': 710,
      'home_breakdown': {
        'name': 'Brazil',
        'power_score': 720,
        'elo': 1500,
        'breakdown': '',
      },
      'away_breakdown': {
        'name': 'France',
        'power_score': 710,
        'elo': 1490,
        'breakdown': '',
      },
      'home_xg': 1.5,
      'away_xg': 1.3,
      'probabilities_1x2': {
        'home_win': 38.0,
        'draw': 28.0,
        'away_win': 34.0,
      },
      'outcome_explanations': {
        'home_win': 'h',
        'draw': 'd',
        'away_win': 'a',
      },
      'top_scores': [
        {'score': '1-1', 'probability': 12.0, 'explanation': ''},
      ],
      'score_coverage': {
        'target_percent': 50.0,
        'achieved_percent': 50.0,
        'scores': ['1-1'],
      },
      ...extra,
    });
  }

  test('MarketTabViewModel unavailable when no probability diagnostics', () {
    final vm = MarketTabViewModel.fromPredictionResult(baseResult({}));
    expect(vm.marketDataAvailable, isFalse);
    expect(vm.statusMessage, 'לא מחובר');
    expect(vm.bookmakers, isEmpty);
  });

  test('MarketTabViewModel builds consensus quote from probability diagnostics', () {
    final result = baseResult({
      'probability_diagnostics': {
        'probability_sum': 100,
        'probability_sum_valid': true,
        'odds_available': true,
        'odds_affect_prediction': false,
        'odds_blend_applied': false,
        'raw_probabilities_1x2': {
          'home_win': 40.0,
          'draw': 27.0,
          'away_win': 33.0,
        },
        'final_probabilities_1x2': {
          'home_win': 38.0,
          'draw': 28.0,
          'away_win': 34.0,
        },
        'market_probabilities_1x2': {
          'home_win': 35.0,
          'draw': 30.0,
          'away_win': 35.0,
        },
        'odds_source': 'the_odds_api',
        'coherence_warnings': [],
      },
    });

    final vm = MarketTabViewModel.fromPredictionResult(result);
    expect(vm.marketDataAvailable, isTrue);
    expect(vm.bookmakers, hasLength(1));
    expect(vm.bookmakers.first.isConsensus, isTrue);
    expect(vm.marketConsensus1x2?['draw'], 30.0);
    expect(vm.oddsAffectPrediction, isFalse);
  });

  test('PredictionResult parses probability and future market diagnostics', () {
    final result = baseResult({
      'probability_diagnostics': {
        'probability_sum': 100,
        'probability_sum_valid': true,
        'odds_available': true,
        'odds_affect_prediction': false,
        'odds_blend_applied': false,
        'raw_probabilities_1x2': {'home_win': 40, 'draw': 30, 'away_win': 30},
        'final_probabilities_1x2': {'home_win': 40, 'draw': 30, 'away_win': 30},
        'coherence_warnings': [],
      },
      'market_diagnostics': {
        'available': true,
        'status': 'ok',
        'primary_source': 'the_odds_api',
        'blend_mode': 'diagnostic_only',
        'bookmakers': [
          {
            'id': 'bet365',
            'display_name': 'Bet365',
            'region': 'eu',
            'home_decimal_odds': 2.5,
            'draw_decimal_odds': 3.2,
            'away_decimal_odds': 2.9,
            'implied_1x2_percent': {
              'home_win': 36.0,
              'draw': 28.0,
              'away_win': 31.0,
            },
          },
        ],
      },
    });

    expect(result.probabilityDiagnostics?.oddsAvailable, isTrue);
    expect(result.marketDiagnostics?.bookmakers, hasLength(1));
    expect(result.marketDiagnostics?.bookmakers.first.displayName, 'Bet365');
  });
}
