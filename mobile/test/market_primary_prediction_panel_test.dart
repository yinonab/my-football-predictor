import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/models/venue_mode.dart';
import 'package:football_predictor/widgets/market_primary_prediction_panel.dart';
import 'package:football_predictor/widgets/prediction_market_panel.dart';
import 'package:football_predictor/widgets/prediction_results_view.dart';

void main() {
  Map<String, dynamic> marketPrimaryBlock({
    bool applied = true,
    String reason = 'applied',
  }) {
    return {
      'applied': applied,
      'reason': reason,
      'market_weight_pct': 70,
      'model_weight_pct': 30,
      'selected_score': '1-0',
      'selected_outcome': 'home_win',
      'market_favorite': 'France',
      'confidence': 'GREEN',
      'market_goal_trend': 'under_2_5',
      'btts_signal': 'no',
      'spread_signal': 'slight_home_favorite',
      'explanation':
          'Market odds favored France overall, while goal markets pointed to a relatively low-scoring match.',
      'inputs': {
        'h2h': {'home': 41.3, 'draw': 29.5, 'away': 29.2},
        'totals': {'line': 2.5, 'over': 48.0, 'under': 52.0},
        'btts': {'yes': 45.0, 'no': 55.0},
        'spread': -0.5,
      },
      'top_scores': [
        {'score': '1-0', 'probability': 12.4},
        {'score': '2-1', 'probability': 10.1},
        {'score': '1-1', 'probability': 9.8},
      ],
      'notes': [],
    };
  }

  PredictionResult baseResult(Map<String, dynamic> extra) {
    return PredictionResult.fromJson({
      'home_team': 'France',
      'away_team': 'Spain',
      'home_power': 994,
      'away_power': 1006,
      'home_breakdown': {
        'name': 'France',
        'power_score': 994,
        'elo': 1840,
        'breakdown': '',
      },
      'away_breakdown': {
        'name': 'Spain',
        'power_score': 1006,
        'elo': 1808,
        'breakdown': '',
      },
      'home_xg': 1.08,
      'away_xg': 1.02,
      'probabilities_1x2': {
        'home_win': 34.5,
        'draw': 34.0,
        'away_win': 31.5,
      },
      'outcome_explanations': {
        'home_win': 'h',
        'draw': 'd',
        'away_win': 'a',
      },
      'top_scores': [
        {'score': '1-1', 'probability': 15.5, 'explanation': ''},
        {'score': '0-0', 'probability': 14.2, 'explanation': ''},
      ],
      'score_coverage': {
        'target_percent': 50.0,
        'achieved_percent': 50.0,
        'scores': ['1-1'],
      },
      'scoreline_decision': {
        'favorite_outcome': 'home_win',
        'favorite_outcome_probability': 34.5,
        'second_outcome': 'draw',
        'second_outcome_probability': 34.0,
        'outcome_margin': 0.5,
        'confidence_label': 'low',
        'primary_predicted_score': {
          'home_goals': 1,
          'away_goals': 1,
          'probability': 15.5,
          'outcome': 'draw',
        },
        'primary_score_reason': 'balanced',
        'warnings': [],
      },
      ...extra,
    });
  }

  test('PredictionResult parses market_primary_prediction', () {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(),
    });
    final block = result.marketPrimaryPrediction!;
    expect(block.applied, isTrue);
    expect(block.selectedScore, '1-0');
    expect(block.marketWeightPct, 70);
    expect(block.inputs.h2h.home, 41.3);
    expect(block.topScores.length, 3);
  });

  testWidgets('Market primary panel shows selected score and signals', (
    tester,
  ) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(),
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: MarketPrimaryPredictionPanel(result: result),
          ),
        ),
      ),
    );
    expect(find.text('תחזית שוק'), findsOneWidget);
    expect(find.text('1-0'), findsWidgets);
    expect(find.textContaining('France'), findsWidgets);
    expect(find.textContaining('70% שוק'), findsOneWidget);
    expect(find.textContaining('GREEN'), findsOneWidget);
    expect(find.textContaining('Market odds favored France'), findsOneWidget);
    expect(find.textContaining('תוצאות מובילות לפי שוק'), findsOneWidget);
  });

  testWidgets('applied=false shows safe fallback', (tester) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        applied: false,
        reason: 'quality_below_minimum',
      ),
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.textContaining('תחזית שוק אינה זמינה'), findsOneWidget);
  });

  testWidgets('missing block shows unavailable message', (tester) async {
    final result = baseResult({});
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.text('תחזית שוק אינה זמינה למשחק זה'), findsOneWidget);
  });

  testWidgets('Market tab unchanged when market primary present', (
    tester,
  ) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(),
      'market_diagnostics': {
        'available': true,
        'status': 'ok',
        'primary_source': 'rapidapi_odds_feed',
        'consensus_1x2_percent': {
          'home_win': 41.3,
          'draw': 29.5,
          'away_win': 29.2,
        },
        'bookmakers': [],
        'notes': [],
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
    expect(find.text('שוק ההימורים'), findsOneWidget);
    expect(find.text('תחזית שוק'), findsNothing);
  });

  testWidgets('New tab appears in results view', (tester) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(),
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: PredictionResultsView(
              result: result,
              venueMode: VenueMode.neutral,
            ),
          ),
        ),
      ),
    );
    expect(find.text('תחזית שוק'), findsOneWidget);
    await tester.tap(find.text('תחזית שוק'));
    await tester.pumpAndSettle();
    expect(find.textContaining('תוצאה מומלצת לפי שוק'), findsOneWidget);
  });

  testWidgets('Prediction tab still shows primary score card', (tester) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(),
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: PredictionResultsView(
              result: result,
              venueMode: VenueMode.neutral,
            ),
          ),
        ),
      ),
    );
    expect(find.text('תחזית'), findsOneWidget);
    expect(find.textContaining('תוצאות אפשריות'), findsOneWidget);
  });
}
