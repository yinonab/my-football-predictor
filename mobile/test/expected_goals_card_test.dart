import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/widgets/prediction_insight_sections.dart';

PredictionResult _resultWithBaseXg() {
  return PredictionResult.fromJson({
    'home_team': 'Spain (ספרד)',
    'away_team': 'Saudi Arabia (ערב הסעודית)',
    'home_power': 900.0,
    'away_power': 650.0,
    'home_breakdown': {
      'name': 'Spain',
      'power_score': 900.0,
      'elo': 1900.0,
      'breakdown': 'test',
    },
    'away_breakdown': {
      'name': 'Saudi Arabia',
      'power_score': 650.0,
      'elo': 1500.0,
      'breakdown': 'test',
    },
    'home_xg': 4.09,
    'away_xg': 0.92,
    'base_home_xg': 1.91,
    'base_away_xg': 0.69,
    'blowout_adjustment_applied': true,
    'adjusted_home_xg': 4.09,
    'adjusted_away_xg': 0.92,
    'probabilities_1x2': {
      'home_win': 78.0,
      'draw': 12.0,
      'away_win': 10.0,
    },
    'outcome_explanations': {
      'home_win': 'h',
      'draw': 'd',
      'away_win': 'a',
    },
    'top_scores': [
      {'score': '4-0', 'probability': 6.8, 'explanation': ''},
    ],
    'score_coverage': {
      'target_percent': 50.0,
      'achieved_percent': 50.0,
      'scores': ['4-0'],
    },
  });
}

PredictionResult _resultWithoutBaseXg() {
  return PredictionResult.fromJson({
    'home_team': 'Netherlands (הולנד)',
    'away_team': 'Sweden (שוודיה)',
    'home_power': 800.0,
    'away_power': 780.0,
    'home_breakdown': {
      'name': 'Netherlands',
      'power_score': 800.0,
      'elo': 1800.0,
      'breakdown': 'test',
    },
    'away_breakdown': {
      'name': 'Sweden',
      'power_score': 780.0,
      'elo': 1750.0,
      'breakdown': 'test',
    },
    'home_xg': 1.6,
    'away_xg': 1.2,
    'probabilities_1x2': {
      'home_win': 45.0,
      'draw': 28.0,
      'away_win': 27.0,
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
  });
}

void main() {
  test('PredictionResult parses base xG fields', () {
    final result = _resultWithBaseXg();
    expect(result.baseHomeXg, 1.91);
    expect(result.baseAwayXg, 0.69);
    expect(result.blowoutAdjustmentApplied, isTrue);
    expect(result.adjustedHomeXg, 4.09);
    expect(result.homeXg, 4.09);
  });

  testWidgets('ExpectedGoalsCard shows base and adjusted rows', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ExpectedGoalsCard(result: _resultWithBaseXg()),
        ),
      ),
    );

    expect(find.text('שערים צפויים'), findsOneWidget);
    expect(find.text('xG בסיסי'), findsOneWidget);
    expect(find.text('אחרי התאמה לתוצאה'), findsOneWidget);
    expect(find.textContaining('1.91'), findsOneWidget);
    expect(find.textContaining('4.09'), findsOneWidget);
  });

  testWidgets('ExpectedGoalsCard works without base xG', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ExpectedGoalsCard(result: _resultWithoutBaseXg()),
        ),
      ),
    );

    expect(find.text('xG בסיסי'), findsNothing);
    expect(find.textContaining('1.6'), findsOneWidget);
  });
}
