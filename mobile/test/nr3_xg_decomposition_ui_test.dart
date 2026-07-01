import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/widgets/prediction_insight_sections.dart';

Map<String, dynamic> _nr3Response({
  required bool fusionOn,
  required double homeXg,
  required double awayXg,
}) {
  final fusionStatus = fusionOn ? 'applied' : 'disabled';
  return {
    'home_team': 'Belgium',
    'away_team': 'Senegal',
    'home_power': 850.0,
    'away_power': 780.0,
    'home_breakdown': {
      'name': 'Belgium',
      'power_score': 850.0,
      'elo': 1800.0,
      'breakdown': 'test',
    },
    'away_breakdown': {
      'name': 'Senegal',
      'power_score': 780.0,
      'elo': 1700.0,
      'breakdown': 'test',
    },
    'home_xg': homeXg,
    'away_xg': awayXg,
    'base_home_xg': 1.73,
    'base_away_xg': 0.87,
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
      {'score': '1-0', 'probability': 12.0, 'explanation': ''},
    ],
    'score_coverage': {
      'target_percent': 50.0,
      'achieved_percent': 50.0,
      'scores': ['1-0'],
    },
    'model_diagnostics': {
      'model_version': 'v2.3.0-nr3-fcc-served',
      'nr3_xg_decomposition': {
        'active_model': 'v2.3.0-nr3-fcc-served',
        'home_team': 'Belgium',
        'away_team': 'Senegal',
        'nr3_base': {
          'home_xg': 1.42,
          'away_xg': 0.78,
          'label': 'בסיס NR3 לפני התאמות',
        },
        'adjustments': [
          {
            'name': 'fusion_blowout',
            'display_name': 'Goliath / Fusion',
            'status': fusionStatus,
            'before_home_xg': 1.37,
            'before_away_xg': 0.76,
            'after_home_xg': homeXg,
            'after_away_xg': awayXg,
            'delta_home_xg': homeXg - 1.37,
            'delta_away_xg': awayXg - 0.76,
            'explanation': fusionOn ? 'אות גולנט משולב' : 'כבוי בהגדרות המשתמש',
          },
        ],
        'final': {
          'home_xg': homeXg,
          'away_xg': awayXg,
          'label': 'xG סופי לחיזוי',
        },
        'legacy_reference': {
          'home_xg': 1.73,
          'away_xg': 0.87,
          'label': 'ייחוס מודל ישן / Maher',
          'note': 'להשוואה בלבד — לא משמש כחישוב הפעיל',
        },
      },
    },
  };
}

void main() {
  test('PredictionResult parses nr3_xg_decomposition', () {
    final result = PredictionResult.fromJson(_nr3Response(
      fusionOn: true,
      homeXg: 1.60,
      awayXg: 0.73,
    ));
    expect(result.nr3XgDecomposition, isNotNull);
    expect(result.nr3XgDecomposition!.nr3Base.label, 'בסיס NR3 לפני התאמות');
    expect(result.nr3XgDecomposition!.legacyReference.note, contains('להשוואה בלבד'));
  });

  testWidgets('NR3 card shows final xG label and breakdown', (tester) async {
    final result = PredictionResult.fromJson(_nr3Response(
      fusionOn: true,
      homeXg: 1.60,
      awayXg: 0.73,
    ));
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: ExpectedGoalsCard(result: result)),
      ),
    );

    expect(find.text('xG סופי לחיזוי'), findsOneWidget);
    expect(find.textContaining('1.60'), findsWidgets);
    expect(find.text('פירוט חישוב NR3'), findsOneWidget);
    await tester.tap(find.text('פירוט חישוב NR3'));
    await tester.pumpAndSettle();
    expect(find.text('בסיס NR3 לפני התאמות'), findsOneWidget);
    expect(find.text('ייחוס מודל ישן / Maher'), findsOneWidget);
    expect(find.textContaining('להשוואה בלבד'), findsOneWidget);
    expect(find.text('xG בסיסי'), findsNothing);
  });

  testWidgets('legacy model does not show NR3 breakdown', (tester) async {
    final result = PredictionResult.fromJson({
      'home_team': 'Belgium',
      'away_team': 'Senegal',
      'home_power': 850.0,
      'away_power': 780.0,
      'home_breakdown': {
        'name': 'Belgium',
        'power_score': 850.0,
        'elo': 1800.0,
        'breakdown': 'test',
      },
      'away_breakdown': {
        'name': 'Senegal',
        'power_score': 780.0,
        'elo': 1700.0,
        'breakdown': 'test',
      },
      'home_xg': 1.73,
      'away_xg': 0.87,
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
        {'score': '1-0', 'probability': 12.0, 'explanation': ''},
      ],
      'score_coverage': {
        'target_percent': 50.0,
        'achieved_percent': 50.0,
        'scores': ['1-0'],
      },
      'model_diagnostics': {
        'model_version': 'v2.2.0-fifa-points-anchor',
      },
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: ExpectedGoalsCard(result: result)),
      ),
    );

    expect(find.text('שערים צפויים'), findsOneWidget);
    expect(find.text('פירוט חישוב NR3'), findsNothing);
    expect(find.text('ייחוס מודל ישן / Maher'), findsNothing);
  });
}
