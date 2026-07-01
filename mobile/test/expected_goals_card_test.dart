import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/widgets/prediction_insight_sections.dart';

PredictionResult _legacyResult() {
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
  testWidgets('ExpectedGoalsCard works for legacy model without NR3', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ExpectedGoalsCard(result: _legacyResult()),
        ),
      ),
    );

    expect(find.text('שערים צפויים'), findsOneWidget);
    expect(find.textContaining('1.6'), findsOneWidget);
    expect(find.text('פירוט חישוב NR3'), findsNothing);
  });
}
