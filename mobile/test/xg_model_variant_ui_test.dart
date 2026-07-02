import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/models/venue_mode.dart';
import 'package:football_predictor/widgets/prediction_results_view.dart';

Map<String, dynamic> _baseResponse({Map<String, dynamic>? modelDiagnostics}) {
  return {
    'home_team': 'France',
    'away_team': 'Haiti',
    'home_power': 1000.0,
    'away_power': 700.0,
    'home_breakdown': {
      'name': 'France',
      'power_score': 1000.0,
      'elo': 1900.0,
      'breakdown': 'test',
    },
    'away_breakdown': {
      'name': 'Haiti',
      'power_score': 700.0,
      'elo': 1500.0,
      'breakdown': 'test',
    },
    'home_xg': 2.5,
    'away_xg': 0.5,
    'base_home_xg': 2.5,
    'base_away_xg': 0.5,
    'probabilities_1x2': {
      'home_win': 80.0,
      'draw': 12.0,
      'away_win': 8.0,
    },
    'outcome_explanations': {
      'home_win': 'h',
      'draw': 'd',
      'away_win': 'a',
    },
    'top_scores': [
      {'score': '2-0', 'probability': 20.0, 'explanation': ''},
    ],
    'score_coverage': {
      'target_percent': 50.0,
      'achieved_percent': 50.0,
      'scores': ['2-0'],
    },
    'scoreline_decision': {
      'favorite_outcome': 'home',
      'favorite_outcome_probability': 80.0,
      'second_outcome': 'draw',
      'second_outcome_probability': 12.0,
      'outcome_margin': 68.0,
      'confidence_label': 'high',
      'primary_predicted_score': {
        'home_goals': 2,
        'away_goals': 0,
        'probability': 20.0,
        'outcome': 'home',
      },
      'primary_score_reason': 'test',
      'top_exact_score_overall': {
        'home_goals': 2,
        'away_goals': 0,
        'probability': 20.0,
        'outcome': 'home',
      },
      'top_exact_score_differs_from_primary': false,
      'underdog_scores_probability': 30.0,
      'both_teams_score_probability': 25.0,
      'favorite_goal_band_probabilities': {
        'favorite_2_plus': 55.0,
        'favorite_3_plus': 20.0,
      },
      'favorite_outcome_top_scores': [],
    },
    if (modelDiagnostics != null) 'model_diagnostics': modelDiagnostics,
  };
}

Map<String, dynamic> _matchupPayload() {
  return {
    'active_model': 'matchup_relative_xg_v1',
    'home_team': 'France',
    'away_team': 'Haiti',
    'favorite_team': 'France',
    'underdog_team': 'Haiti',
    'home_goal_capability': 'HIGH',
    'away_goal_capability': 'LOW',
    'favorite_goal_capability': 'HIGH',
    'underdog_goal_capability': 'LOW',
    'favorite_multi_goal_capability': 'MEDIUM',
    'favorite_clean_sheet_reliability': 'HIGH',
    'clean_sheet_risk': 'LOW',
    'btts_likelihood': 'LOW',
    'probabilities': {
      'home_scores_probability': 90.0,
      'away_scores_probability': 30.0,
      'favorite_scores_probability': 90.0,
      'underdog_scores_probability': 30.0,
      'favorite_scores_2_plus_probability': 50.0,
      'favorite_scores_3_plus_probability': 20.0,
      'btts_probability': 25.0,
    },
    'matchup_inputs': {
      'served_home_xg': 2.5,
      'served_away_xg': 0.5,
      'maher_reference_home_xg': 2.0,
      'maher_reference_away_xg': 0.6,
      'power_gap': 300.0,
    },
    'reason_codes': ['UNDERDOG_XG_LOW'],
    'summary': {
      'title': 'יכולת הבקעה לפי מפגש',
      'short_text': 'test',
      'clean_sheet_text': 'test',
      'underdog_text': 'test',
      'favorite_text': 'test',
    },
  };
}

Widget _wrap(Widget child) {
  return MaterialApp(
    home: Scaffold(
      body: SingleChildScrollView(child: child),
    ),
  );
}

void main() {
  testWidgets('result page shows active model badge', (tester) async {
    final result = PredictionResult.fromJson(
      _baseResponse(
        modelDiagnostics: {
          'model_version': 'matchup_relative_xg_v1',
          'active_xg_source': 'matchup_relative_v1',
          'model_variant': 'matchup_relative_v1',
        },
      ),
    );

    await tester.pumpWidget(
      _wrap(
        PredictionResultsView(
          result: result,
          venueMode: VenueMode.neutral,
        ),
      ),
    );

    expect(find.text('מודל פעיל: Matchup Relative — ניסיוני'), findsOneWidget);
  });

  testWidgets('matchup goal capability card still renders with badge', (
    tester,
  ) async {
    final result = PredictionResult.fromJson(
      _baseResponse(
        modelDiagnostics: {
          'model_variant': 'matchup_relative_v1',
          'active_xg_source': 'matchup_relative_v1',
          'matchup_goal_capability': _matchupPayload(),
        },
      ),
    );

    await tester.pumpWidget(
      _wrap(
        PredictionResultsView(
          result: result,
          venueMode: VenueMode.neutral,
        ),
      ),
    );

    expect(find.text('מודל פעיל: Matchup Relative — ניסיוני'), findsOneWidget);
    expect(find.text('יכולת הבקעה לפי מפגש'), findsOneWidget);
  });
}
