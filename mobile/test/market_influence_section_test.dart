import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/widgets/market_influence_section.dart';
import 'package:football_predictor/widgets/prediction_market_panel.dart';

void main() {
  PredictionResult baseResult(Map<String, dynamic> extra) {
    return PredictionResult.fromJson({
      'home_team': 'Norway',
      'away_team': 'England',
      'home_power': 700,
      'away_power': 820,
      'home_breakdown': {
        'name': 'Norway',
        'power_score': 700,
        'elo': 1400,
        'breakdown': '',
      },
      'away_breakdown': {
        'name': 'England',
        'power_score': 820,
        'elo': 1500,
        'breakdown': '',
      },
      'home_xg': 0.8,
      'away_xg': 2.1,
      'probabilities_1x2': {
        'home_win': 18.0,
        'draw': 24.0,
        'away_win': 58.0,
      },
      'outcome_explanations': {
        'home_win': 'h',
        'draw': 'd',
        'away_win': 'a',
      },
      'top_scores': [
        {'score': '0-1', 'probability': 14.17, 'explanation': ''},
        {'score': '0-2', 'probability': 11.70, 'explanation': ''},
        {'score': '1-1', 'probability': 10.71, 'explanation': ''},
      ],
      'score_coverage': {
        'target_percent': 50.0,
        'achieved_percent': 50.0,
        'scores': ['0-1'],
      },
      ...extra,
    });
  }

  final influencePayload = {
    'market_influence_applied': true,
    'quality_band': 'GREEN',
    'influence_weight_pct': 50,
    'provider_event_id': '619963',
    'cache_status': 'miss',
    'provider_call_count': 1,
    'primary_score_reason': 'market_influence_applied',
    'explanation': {
      'title': 'Market-adjusted prediction',
      'summary':
          'Live market signals strengthened England as the likely winner.',
      'signal_label': 'Strong market signal',
      'influence_label': '50% market influence',
      'selected_score_label': 'Selected market-adjusted score: 0-1',
      'details': [
        'Market quality: strong market signal.',
        'The exact-score blend used 50% market weight.',
      ],
    },
  };

  test('PredictionResult parses market_influence block', () {
    final result = baseResult({
      'market_influence': influencePayload,
      'scoreline_decision': {
        'favorite_outcome': 'away_win',
        'favorite_outcome_probability': 58.0,
        'second_outcome': 'draw',
        'second_outcome_probability': 24.0,
        'outcome_margin': 34.0,
        'confidence_label': 'high',
        'primary_predicted_score': {
          'home_goals': 0,
          'away_goals': 1,
          'probability': 14.17,
          'outcome': 'away_win',
        },
        'primary_score_reason': 'market_influence_applied',
      },
    });

    expect(result.marketInfluence?.marketInfluenceApplied, isTrue);
    expect(result.marketInfluence?.qualityBand, 'GREEN');
    expect(result.marketInfluence?.explanation?.title, 'Market-adjusted prediction');
    expect(result.marketInfluence?.explanation?.details, hasLength(2));
  });

  test('MarketInfluenceSection hidden when influence not applied', () {
    final result = baseResult({});
    expect(MarketInfluenceSection.shouldShow(result), isFalse);
  });

  testWidgets('Market tab shows influence section when applied', (tester) async {
    final result = baseResult({
      'market_influence': influencePayload,
      'scoreline_decision': {
        'favorite_outcome': 'away_win',
        'favorite_outcome_probability': 58.0,
        'second_outcome': 'draw',
        'second_outcome_probability': 24.0,
        'outcome_margin': 34.0,
        'confidence_label': 'high',
        'primary_predicted_score': {
          'home_goals': 0,
          'away_goals': 1,
          'probability': 14.17,
          'outcome': 'away_win',
        },
        'primary_score_reason': 'market_influence_applied',
      },
    });

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: PredictionMarketPanel(result: result),
          ),
        ),
      ),
    );

    expect(find.text('Market-adjusted prediction'), findsOneWidget);
    expect(find.text('Strong market signal'), findsOneWidget);
    expect(find.text('0-1'), findsWidgets);
    expect(find.text('שוק ההימורים'), findsOneWidget);
    expect(find.textContaining('provider_event_id'), findsNothing);
    expect(find.textContaining('cache_status'), findsNothing);
  });

  testWidgets('Market tab unchanged when market_influence absent', (tester) async {
    final result = baseResult({});

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: PredictionMarketPanel(result: result),
        ),
      ),
    );

    expect(find.text('Market-adjusted prediction'), findsNothing);
    expect(find.text('שוק ההימורים'), findsOneWidget);
  });
}
