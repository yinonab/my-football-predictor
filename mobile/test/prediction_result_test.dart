import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';

void main() {
  test('PredictionResult parses scoreline_decision and diagnostics', () {
    final result = PredictionResult.fromJson({
      'home_team': 'Canada',
      'away_team': 'Qatar',
      'home_power': 712.0,
      'away_power': 664.0,
      'home_breakdown': {
        'name': 'Canada',
        'power_score': 712.0,
        'elo': 1487.0,
        'breakdown': 'test',
      },
      'away_breakdown': {
        'name': 'Qatar',
        'power_score': 664.0,
        'elo': 1380.0,
        'breakdown': 'test',
      },
      'home_xg': 1.6,
      'away_xg': 1.0,
      'probabilities_1x2': {
        'home_win': 49.8,
        'draw': 27.7,
        'away_win': 22.5,
      },
      'outcome_explanations': {
        'home_win': 'home',
        'draw': 'draw',
        'away_win': 'away',
      },
      'top_scores': [
        {'score': '1-1', 'probability': 13.2, 'explanation': 'draw likely'},
      ],
      'score_coverage': {
        'target_percent': 50.0,
        'achieved_percent': 51.8,
        'scores': ['1-1', '1-0'],
      },
      'scoreline_decision': {
        'favorite_outcome': 'home_win',
        'favorite_outcome_probability': 49.8,
        'second_outcome': 'draw',
        'second_outcome_probability': 27.7,
        'outcome_margin': 22.1,
        'confidence_label': 'medium',
        'primary_predicted_score': {
          'home_goals': 1,
          'away_goals': 0,
          'probability': 10.7,
          'outcome': 'home_win',
        },
        'primary_score_reason': 'קנדה מובילה',
        'top_exact_score_overall': {
          'home_goals': 1,
          'away_goals': 1,
          'probability': 13.2,
          'outcome': 'draw',
        },
        'top_exact_score_differs_from_primary': true,
        'favorite_outcome_top_scores': [
          {
            'home_goals': 1,
            'away_goals': 0,
            'probability': 10.7,
            'outcome': 'home_win',
          },
        ],
        'warnings': ['CONTEXT_LIMITED'],
      },
      'match_context_diagnostics': {
        'fixture_status': 'unknown',
        'prediction_valid': true,
        'prediction_mode': 'unknown',
        'fixture_source_available': false,
        'venue_context_available': false,
        'neutral_ground_requested': true,
        'host_advantage_applied': false,
        'home_advantage_value': 0,
        'warnings': ['FIXTURE_STATE_UNAVAILABLE'],
      },
    });

    expect(result.scorelineDecision, isNotNull);
    expect(result.scorelineDecision!.primaryPredictedScore?.homeGoals, 1);
    expect(result.scorelineDecision!.topExactScoreDiffersFromPrimary, isTrue);
    expect(result.matchContextDiagnostics?.fixtureStatus, 'unknown');
    expect(result.matchContextDiagnostics?.predictionValid, isTrue);
  });

  test('PredictionResult works without scoreline_decision', () {
    final result = PredictionResult.fromJson({
      'home_team': 'A',
      'away_team': 'B',
      'home_power': 700.0,
      'away_power': 680.0,
      'home_breakdown': {
        'name': 'A',
        'power_score': 700.0,
        'elo': 1400.0,
        'breakdown': 'test',
      },
      'away_breakdown': {
        'name': 'B',
        'power_score': 680.0,
        'elo': 1380.0,
        'breakdown': 'test',
      },
      'home_xg': 1.4,
      'away_xg': 1.2,
      'probabilities_1x2': {'home_win': 40.0, 'draw': 30.0, 'away_win': 30.0},
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
    });

    expect(result.scorelineDecision, isNull);
    expect(result.matchContextDiagnostics, isNull);
    expect(result.topScores.first.score, '1-1');
  });
}
