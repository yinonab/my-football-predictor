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
    String selectedScore = '2-1',
    String selectedOutcome = 'home_win',
    String spreadSignal = 'strong_home_favorite',
    String marketGoalTrend = 'neutral',
    String bttsSignal = 'yes',
    List<Map<String, dynamic>>? topScores,
  }) {
    return {
      'applied': applied,
      'reason': reason,
      'market_weight_pct': 70,
      'model_weight_pct': 30,
      'selected_score': selectedScore,
      'selected_outcome': selectedOutcome,
      'market_favorite': 'France',
      'confidence': 'GREEN',
      'market_goal_trend': marketGoalTrend,
      'btts_signal': bttsSignal,
      'spread_signal': spreadSignal,
      'explanation':
          'Market odds favored France overall, while goal markets pointed to a neutral goal environment and both teams likely to score. The market-primary prediction is therefore 2-1 (France win).',
      'inputs': {
        'h2h': {'home': 40.78, 'draw': 29.53, 'away': 29.69},
        'totals': {'line': 2.5, 'over': 49.76, 'under': 50.24},
        'btts': {'yes': 56.56, 'no': 43.44},
        'spread': 0.0,
      },
      'top_scores': topScores ??
          [
            {'score': '2-1', 'probability': 33.7},
            {'score': '2-0', 'probability': 20.5},
            {'score': '3-1', 'probability': 19.2},
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
    expect(block.selectedScore, '2-1');
    expect(block.marketWeightPct, 70);
    expect(block.inputs.h2h.home, 40.78);
    expect(block.topScores.length, 3);
    expect(block.topScores.first.score, '2-1');
  });

  test('spreadSignalLabel translates strong_home_favorite with team name', () {
    expect(
      spreadSignalLabel(
        signal: 'strong_home_favorite',
        homeTeam: 'France',
        awayTeam: 'Spain',
      ),
      'France פייבוריטית חזקה',
    );
    expect(
      spreadSignalLabel(signal: 'strong_home_favorite'),
      'פייבוריט ביתי חזק',
    );
  });

  test('signal label helpers handle null values', () {
    expect(marketGoalTrendLabel(null), 'לא זמין');
    expect(bttsSignalLabel(null), 'לא זמין');
    expect(spreadSignalLabel(signal: null), 'לא זמין');
    expect(marketGoalTrendLabel('neutral'), 'ניטרלי');
    expect(bttsSignalLabel('yes'), 'כן');
  });

  test('displayTeamLabel prefers Hebrew in parentheses', () {
    expect(displayTeamLabel('France (צרפת)'), 'צרפת');
    expect(displayTeamLabel('Spain'), 'Spain');
  });

  test('parseSelectedScore formats LTR display', () {
    expect(parseSelectedScore('2-1').ltrDisplay, '2 - 1');
    expect(parseSelectedScore('1-2').homeGoals, 1);
    expect(parseSelectedScore('1-2').awayGoals, 2);
  });

  test('marketPrimaryOutcomeLabelHe maps outcomes', () {
    expect(
      marketPrimaryOutcomeLabelHe(
        outcome: 'home_win',
        homeTeam: 'France',
        awayTeam: 'Spain',
      ),
      'ניצחון France',
    );
    expect(
      marketPrimaryOutcomeLabelHe(
        outcome: 'draw',
        homeTeam: 'France',
        awayTeam: 'Spain',
      ),
      'תיקו',
    );
  });

  testWidgets('Hero shows home score away with team context for home win', (
    tester,
  ) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        selectedScore: '2-1',
        selectedOutcome: 'home_win',
      ),
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
    expect(find.text('France'), findsWidgets);
    expect(find.text('Spain'), findsWidgets);
    expect(find.text('2 - 1'), findsOneWidget);
    expect(find.text('ניצחון France'), findsOneWidget);
    expect(find.text('תוצאה מומלצת לפי השוק'), findsOneWidget);
  });

  testWidgets('Hero shows France 1 - 2 Spain for away win', (tester) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        selectedScore: '1-2',
        selectedOutcome: 'away_win',
        spreadSignal: 'strong_away_favorite',
      ),
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
    expect(find.text('France'), findsWidgets);
    expect(find.text('Spain'), findsWidgets);
    expect(find.text('1 - 2'), findsOneWidget);
    expect(find.text('ניצחון Spain'), findsOneWidget);
  });

  testWidgets('Hero shows France 1 - 1 Spain for draw', (tester) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        selectedScore: '1-1',
        selectedOutcome: 'draw',
      ),
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
    expect(find.text('France'), findsWidgets);
    expect(find.text('Spain'), findsWidgets);
    expect(find.text('1 - 1'), findsOneWidget);
    expect(find.text('תיקו'), findsWidgets);
  });

  testWidgets('Hero uses Hebrew team names when available', (tester) async {
    final result = PredictionResult.fromJson({
      'home_team': 'France (צרפת)',
      'away_team': 'Spain (ספרד)',
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
      ],
      'score_coverage': {
        'target_percent': 50.0,
        'achieved_percent': 50.0,
        'scores': ['1-1'],
      },
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
    expect(find.text('צרפת'), findsWidgets);
    expect(find.text('ספרד'), findsWidgets);
    expect(find.text('ניצחון צרפת'), findsOneWidget);
  });

  testWidgets('Market primary panel shows selected score 2-1 and signals', (
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
    expect(find.text('2 - 1'), findsOneWidget);
    expect(find.text('2-1'), findsWidgets);
    expect(find.textContaining('70% שוק'), findsOneWidget);
    expect(find.textContaining('GREEN'), findsOneWidget);
    expect(find.textContaining('Market odds favored France'), findsOneWidget);
    expect(find.textContaining('תוצאות מובילות לפי שוק'), findsOneWidget);
    expect(find.textContaining('מעל/מתחת 2.5: ניטרלי'), findsOneWidget);
    expect(find.textContaining('BTTS: כן'), findsOneWidget);
    expect(find.textContaining('האנדיקפ: France פייבוריטית חזקה'), findsOneWidget);
    expect(find.textContaining('strong_home_favorite'), findsNothing);
    expect(find.textContaining('strong home favorite'), findsNothing);
  });

  testWidgets('Top score rows render in deterministic order', (tester) async {
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

    final scoreFinder = find.byWidgetPredicate(
      (widget) =>
          widget is Text &&
          RegExp(r'^\d+-\d+$').hasMatch(widget.data ?? ''),
    );
    final scores = scoreFinder
        .evaluate()
        .map((e) => (e.widget as Text).data)
        .whereType<String>()
        .toList();
    expect(scores, contains('2-1'));
    expect(scores, contains('2-0'));
    expect(scores, contains('3-1'));
    expect(scores.indexOf('2-1'), lessThan(scores.indexOf('2-0')));
    expect(scores.indexOf('2-0'), lessThan(scores.indexOf('3-1')));
  });

  testWidgets('Market direction uses team names with percentages', (
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
    expect(find.text('France'), findsWidgets);
    expect(find.text('Spain'), findsWidgets);
    expect(find.text('תיקו'), findsOneWidget);
    expect(find.text('40.8%'), findsOneWidget);
    expect(find.text('29.5%'), findsOneWidget);
    expect(find.text('29.7%'), findsOneWidget);
  });

  testWidgets('applied=false quality_below_minimum shows dedicated fallback', (
    tester,
  ) async {
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
    expect(find.text('איכות נתוני השוק נמוכה'), findsOneWidget);
    expect(find.textContaining('אינם מספיק אמינים'), findsOneWidget);
    expect(find.textContaining('quality_below_minimum'), findsNothing);
  });

  testWidgets('resolver_no_match shows transient fallback with diagnostics', (
    tester,
  ) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        applied: false,
        reason: 'market_unavailable',
      ),
      'market_influence_status': {
        'attempted': true,
        'applied': false,
        'reason': 'resolver_no_match',
        'provider': 'rapidapi_odds_feed',
        'resolver_pages_fetched': 3,
        'resolver_events_seen': 300,
        'resolver_discovery_status': 'SCHEDULED',
      },
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.text('תחזית שוק לא זמינה זמנית'), findsOneWidget);
    expect(find.textContaining('לא נמצא אירוע שוק מתאים'), findsWidgets);
    expect(find.textContaining('נסה להריץ את החיזוי שוב בעוד דקה'), findsOneWidget);
    expect(find.textContaining('עמודים שנבדקו'), findsOneWidget);
    expect(find.textContaining('3 / 5'), findsOneWidget);
    expect(find.textContaining('אירועים שנבדקו'), findsOneWidget);
    expect(find.textContaining('300'), findsOneWidget);
    expect(find.textContaining('SCHEDULED'), findsOneWidget);
    expect(find.textContaining('rapidapi_odds_feed'), findsOneWidget);
    expect(find.textContaining('resolver_no_match'), findsNothing);
    expect(find.textContaining('market_unavailable'), findsNothing);
  });

  testWidgets('market_unavailable shows regular prediction guidance', (
    tester,
  ) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        applied: false,
        reason: 'market_unavailable',
      ),
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.text('תחזית שוק לא זמינה'), findsOneWidget);
    expect(
      find.textContaining('לא התקבלו נתוני שוק מספיקים'),
      findsOneWidget,
    );
    expect(
      find.textContaining('התחזית הרגילה עדיין זמינה בטאב תחזית'),
      findsOneWidget,
    );
    expect(find.textContaining('market_unavailable'), findsNothing);
  });

  testWidgets('quota_exceeded from legacy diagnostics shows friendly message', (
    tester,
  ) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        applied: false,
        reason: 'market_unavailable',
      ),
      'market_diagnostics': {
        'available': false,
        'status': 'quota_exceeded',
        'primary_source': 'the_odds_api',
        'bookmakers': [],
        'notes': ['quota exceeded on The Odds API'],
      },
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.text('נתוני שוק אינם זמינים כרגע'), findsOneWidget);
    expect(find.textContaining('מגבלת שימוש'), findsOneWidget);
    expect(find.textContaining('quota_exceeded'), findsNothing);
    expect(find.textContaining('The Odds API'), findsNothing);
  });

  testWidgets('resolver miss takes priority over quota diagnostics', (
    tester,
  ) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        applied: false,
        reason: 'market_unavailable',
      ),
      'market_influence_status': {
        'attempted': true,
        'applied': false,
        'reason': 'resolver_no_match',
      },
      'market_diagnostics': {
        'available': false,
        'status': 'quota_exceeded',
        'primary_source': 'the_odds_api',
        'bookmakers': [],
        'notes': [],
      },
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.text('תחזית שוק לא זמינה זמנית'), findsOneWidget);
    expect(find.text('נתוני שוק אינם זמינים כרגע'), findsNothing);
  });

  testWidgets('raw enum reasons are not shown in fallback UI', (tester) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        applied: false,
        reason: 'market_unavailable',
        spreadSignal: 'strong_home_favorite',
      ),
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.textContaining('market_unavailable'), findsNothing);
    expect(find.textContaining('strong_home_favorite'), findsNothing);
    expect(find.textContaining('resolver_no_match'), findsNothing);
  });

  testWidgets('missing block shows generic unavailable fallback', (tester) async {
    final result = baseResult({});
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.text('תחזית שוק לא זמינה'), findsOneWidget);
    expect(find.textContaining('תחזית שוק אינה זמינה למשחק זה'), findsOneWidget);
  });

  testWidgets('null optional influence and diagnostics fields do not crash', (
    tester,
  ) async {
    final result = baseResult({
      'market_primary_prediction': marketPrimaryBlock(
        applied: false,
        reason: 'market_unavailable',
      ),
      'market_influence_status': {
        'attempted': true,
        'applied': false,
        'reason': 'resolver_ambiguous',
      },
    });
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: MarketPrimaryPredictionPanel(result: result),
        ),
      ),
    );
    expect(find.text('תחזית שוק לא זמינה זמנית'), findsOneWidget);
    expect(find.textContaining('נמצאו כמה אירועים אפשריים'), findsWidgets);
  });

  test('PredictionResult parses market_influence_status', () {
    final result = baseResult({
      'market_influence_status': {
        'attempted': true,
        'applied': false,
        'reason': 'resolver_no_match',
        'provider': 'rapidapi_odds_feed',
        'resolver_pages_fetched': 3,
        'resolver_events_seen': 300,
        'resolver_discovery_status': 'SCHEDULED',
      },
    });
    final status = result.marketInfluenceStatus!;
    expect(status.reason, 'resolver_no_match');
    expect(status.provider, 'rapidapi_odds_feed');
    expect(status.resolverPagesFetched, 3);
    expect(status.resolverEventsSeen, 300);
    expect(status.resolverDiscoveryStatus, 'SCHEDULED');
  });

  testWidgets('missing optional signal fields do not crash', (tester) async {
    final block = marketPrimaryBlock();
    block.remove('market_goal_trend');
    block.remove('btts_signal');
    block.remove('spread_signal');
    block['top_scores'] = [];
    final result = baseResult({'market_primary_prediction': block});
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: MarketPrimaryPredictionPanel(result: result),
          ),
        ),
      ),
    );
    expect(find.text('2 - 1'), findsOneWidget);
    expect(find.textContaining('לא זמין'), findsNWidgets(3));
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
    expect(find.textContaining('תוצאה מומלצת לפי השוק'), findsOneWidget);
    expect(find.text('2 - 1'), findsOneWidget);
    expect(find.text('2-1'), findsWidgets);
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
