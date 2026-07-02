import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/models/venue_mode.dart';
import 'package:football_predictor/widgets/matchup_goal_capability_card.dart';
import 'package:football_predictor/widgets/prediction_results_view.dart';

Map<String, dynamic> _baseResponse({Map<String, dynamic>? matchup}) {
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
    'home_xg': 1.73,
    'away_xg': 0.87,
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
      {'score': '2-0', 'probability': 12.0, 'explanation': ''},
      {'score': '2-1', 'probability': 10.0, 'explanation': ''},
    ],
    'score_coverage': {
      'target_percent': 50.0,
      'achieved_percent': 50.0,
      'scores': ['2-0', '2-1'],
    },
    'scoreline_decision': {
      'favorite_outcome': 'home',
      'favorite_outcome_probability': 45.0,
      'second_outcome': 'draw',
      'second_outcome_probability': 28.0,
      'outcome_margin': 17.0,
      'confidence_label': 'medium',
      'primary_predicted_score': {
        'home_goals': 2,
        'away_goals': 0,
        'probability': 12.0,
        'outcome': 'home',
      },
      'primary_score_reason': 'test',
      'top_exact_score_overall': {
        'home_goals': 2,
        'away_goals': 0,
        'probability': 12.0,
        'outcome': 'home',
      },
      'top_exact_score_differs_from_primary': false,
      'underdog_scores_probability': 52.0,
      'both_teams_score_probability': 38.0,
      'favorite_goal_band_probabilities': {
        'favorite_2_plus': 55.0,
        'favorite_3_plus': 20.0,
      },
      'favorite_outcome_top_scores': [
        {
          'home_goals': 2,
          'away_goals': 1,
          'probability': 10.0,
          'outcome': 'home',
        },
      ],
    },
    'model_diagnostics': {
      'model_version': 'v2.3.0-nr3-fcc-served',
      if (matchup != null) 'matchup_goal_capability': matchup,
    },
  };
}

Map<String, dynamic> _matchupPayload() {
  return {
    'active_model': 'v2.3.0-nr3-fcc-served',
    'home_team': 'Belgium',
    'away_team': 'Senegal',
    'favorite_team': 'Belgium',
    'underdog_team': 'Senegal',
    'home_goal_capability': 'HIGH',
    'away_goal_capability': 'MEDIUM',
    'favorite_goal_capability': 'HIGH',
    'underdog_goal_capability': 'HIGH',
    'favorite_multi_goal_capability': 'MEDIUM',
    'favorite_clean_sheet_reliability': 'LOW',
    'clean_sheet_risk': 'HIGH',
    'btts_likelihood': 'MEDIUM',
    'probabilities': {
      'home_scores_probability': 82.0,
      'away_scores_probability': 58.0,
      'favorite_scores_probability': 82.0,
      'underdog_scores_probability': 52.0,
      'favorite_scores_2_plus_probability': 55.0,
      'favorite_scores_3_plus_probability': 20.0,
      'btts_probability': 38.0,
    },
    'matchup_inputs': {
      'served_home_xg': 1.73,
      'served_away_xg': 0.87,
      'maher_reference_home_xg': 1.5,
      'maher_reference_away_xg': 0.9,
      'power_gap': 70.0,
    },
    'reason_codes': [
      'UNDERDOG_XG_MEANINGFUL',
      'FAVORITE_CLEAN_SHEET_RISKY',
    ],
    'summary': {
      'title': 'יכולת הבקעה לפי מפגש',
      'short_text': 'test',
      'clean_sheet_text':
          'הפייבוריט עדיין מוביל בתחזית, אבל שער נקי אינו בטוח.',
      'underdog_text': 'לאנדרדוג יש סיכוי משמעותי להבקיע במשחק הזה.',
      'favorite_text': '',
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
  testWidgets('matchup goal capability card shows key rows', (tester) async {
    final capability = PredictionResult.fromJson(
      _baseResponse(matchup: _matchupPayload()),
    ).matchupGoalCapability!;

    await tester.pumpWidget(
      _wrap(MatchupGoalCapabilityCard(capability: capability)),
    );

    expect(find.text('יכולת הבקעה לפי מפגש'), findsOneWidget);
    expect(find.textContaining('יכולת Belgium להבקיע'), findsOneWidget);
    expect(find.textContaining('יכולת Senegal להבקיע'), findsOneWidget);
    expect(find.text('52%'), findsOneWidget);
    expect(find.text('גבוה'), findsWidgets);
    expect(
      find.text('הפייבוריט עדיין מוביל בתחזית, אבל שער נקי אינו בטוח.'),
      findsOneWidget,
    );
  });

  testWidgets('prediction results renders without overflow', (tester) async {
    final result = PredictionResult.fromJson(
      _baseResponse(matchup: _matchupPayload()),
    );

    await tester.pumpWidget(
      _wrap(
        PredictionResultsView(
          result: result,
          venueMode: VenueMode.neutral,
          isNeutralGround: true,
        ),
      ),
    );

    expect(find.text('תחזית מרכזית'), findsOneWidget);
    expect(find.text('יכולת הבקעה לפי מפגש'), findsOneWidget);
    expect(find.text('הסתברויות עיקריות (1X2)'), findsOneWidget);
    expect(find.text('פרטים טכניים'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('legacy response without matchup diagnostics still renders',
      (tester) async {
    final result = PredictionResult.fromJson(_baseResponse());

    await tester.pumpWidget(
      _wrap(
        PredictionResultsView(
          result: result,
          venueMode: VenueMode.neutral,
          isNeutralGround: true,
        ),
      ),
    );

    expect(find.text('תחזית מרכזית'), findsOneWidget);
    expect(find.text('יכולת הבקעה לפי מפגש'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('technical details collapsed by default', (tester) async {
    final result = PredictionResult.fromJson(
      _baseResponse(matchup: _matchupPayload()),
    );

    await tester.pumpWidget(
      _wrap(
        PredictionResultsView(
          result: result,
          venueMode: VenueMode.neutral,
          isNeutralGround: true,
        ),
      ),
    );

    expect(find.text('קודי סיבה'), findsNothing);

    await tester.scrollUntilVisible(
      find.text('פרטים טכניים'),
      48,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('פרטים טכניים'));
    await tester.pumpAndSettle();

    expect(find.text('קודי סיבה'), findsOneWidget);
    expect(find.textContaining('FAVORITE_CLEAN_SHEET_RISKY'), findsOneWidget);
  });
}
