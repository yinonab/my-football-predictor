import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/models/venue_mode.dart';
import 'package:football_predictor/utils/underdog_scoring_narrative.dart';
import 'package:football_predictor/widgets/prediction_insight_sections.dart';
import 'package:football_predictor/widgets/prediction_results_view.dart';

Map<String, dynamic> _belgiumSenegalPayload({
  required bool goliath,
  required String primaryScore,
  required int primaryHome,
  required int primaryAway,
  required double primaryProb,
  required List<Map<String, dynamic>> topScores,
  double? underdogScoresProbability,
  double? bttsProbability,
}) {
  final parts = primaryScore.split('-');
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
    'home_xg': goliath ? 1.6 : 1.37,
    'away_xg': goliath ? 0.73 : 0.76,
    'probabilities_1x2': {
      'home_win': goliath ? 55.0 : 49.9,
      'draw': goliath ? 28.1 : 30.6,
      'away_win': goliath ? 16.9 : 19.5,
    },
    'outcome_explanations': {
      'home_win': 'h',
      'draw': 'd',
      'away_win': 'a',
    },
    'top_scores': topScores,
    'score_coverage': {
      'target_percent': 50.0,
      'achieved_percent': 50.0,
      'scores': topScores.map((e) => e['score']).toList(),
    },
    'scoreline_decision': {
      'favorite_outcome': 'home_win',
      'favorite_outcome_probability': goliath ? 55.0 : 49.9,
      'second_outcome': 'draw',
      'second_outcome_probability': goliath ? 28.1 : 30.6,
      'outcome_margin': goliath ? 26.9 : 19.3,
      'confidence_label': 'medium',
      'primary_predicted_score': {
        'home_goals': primaryHome,
        'away_goals': primaryAway,
        'probability': primaryProb,
        'outcome': 'home_win',
      },
      'primary_score_reason': 'test',
      'warnings': [],
      if (underdogScoresProbability != null)
        'underdog_scores_probability': underdogScoresProbability,
      if (bttsProbability != null) 'both_teams_score_probability': bttsProbability,
    },
    'model_diagnostics': {
      'model_version': 'v2.3.0-nr3-fcc-served',
      'nr3_xg_decomposition': {
        'active_model': 'v2.3.0-nr3-fcc-served',
        'home_team': 'Belgium',
        'away_team': 'Senegal',
        'nr3_base': {
          'home_xg': 1.34,
          'away_xg': 0.79,
          'label': 'בסיס NR3',
        },
        'adjustments': [],
        'final': {
          'home_xg': goliath ? 1.6 : 1.37,
          'away_xg': goliath ? 0.73 : 0.76,
          'label': 'xG סופי',
        },
        'legacy_reference': {
          'home_xg': 1.73,
          'away_xg': 0.87,
          'label': 'legacy',
          'note': 'note',
        },
      },
    },
  };
}

final _belgiumTopScoresOff = [
  {'score': '1-0', 'probability': 15.03, 'explanation': ''},
  {'score': '1-1', 'probability': 13.71, 'explanation': ''},
  {'score': '0-0', 'probability': 13.22, 'explanation': ''},
  {'score': '2-0', 'probability': 11.19, 'explanation': ''},
  {'score': '2-1', 'probability': 8.5, 'explanation': ''},
];

final _belgiumTopScoresOn = [
  {'score': '1-0', 'probability': 14.43, 'explanation': ''},
  {'score': '0-0', 'probability': 12.91, 'explanation': ''},
  {'score': '2-0', 'probability': 11.8, 'explanation': ''},
  {'score': '1-1', 'probability': 11.66, 'explanation': ''},
  {'score': '2-1', 'probability': 7.97, 'explanation': ''},
];

void main() {
  group('buildUnderdogScoringNarrative logic', () {
    test('clean-sheet primary + ud prob >= 40% shows narrative', () {
      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: false,
        primaryScore: '1-0',
        primaryHome: 1,
        primaryAway: 0,
        primaryProb: 15.03,
        topScores: _belgiumTopScoresOff,
        underdogScoresProbability: 53.22,
        bttsProbability: 40.96,
      ));

      final narrative = buildUnderdogScoringNarrative(result);
      expect(narrative, isNotNull);
      expect(narrative!.underdogTeamName, 'Senegal');
      expect(narrative.underdogScoringProbabilityPercent, 53.22);
      expect(narrative.alternativeScoreText, contains('Belgium 2'));
      expect(narrative.alternativeScoreText, contains('Senegal'));
      expect(narrative.bttsProbabilityPercent, 40.96);
    });

    test('primary where underdog already scores hides narrative', () {
      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: false,
        primaryScore: '2-1',
        primaryHome: 2,
        primaryAway: 1,
        primaryProb: 8.5,
        topScores: _belgiumTopScoresOff,
        underdogScoresProbability: 53.22,
      ));

      expect(buildUnderdogScoringNarrative(result), isNull);
      expect(shouldShowUnderdogScoringNarrative(result), isFalse);
    });

    test('prefers favorite-win ud-scoring line over draw 1-1', () {
      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: true,
        primaryScore: '2-0',
        primaryHome: 2,
        primaryAway: 0,
        primaryProb: 11.8,
        topScores: _belgiumTopScoresOn,
        underdogScoresProbability: 50.21,
      ));

      final narrative = buildUnderdogScoringNarrative(result);
      expect(narrative!.alternativeScoreText, contains('Belgium 2'));
      expect(narrative.alternativeScoreText, isNot(contains('Belgium 1–1')));
    });

    test('derives ud scoring probability from xG when API field missing', () {
      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: false,
        primaryScore: '1-0',
        primaryHome: 1,
        primaryAway: 0,
        primaryProb: 15.03,
        topScores: _belgiumTopScoresOff,
      ));

      final narrative = buildUnderdogScoringNarrative(result);
      expect(narrative, isNotNull);
      expect(
        narrative!.underdogScoringProbabilityPercent,
        closeTo(poissonUnderdogScoresProbabilityPercent(0.76), 0.5),
      );
    });

    test('does not mutate top_scores list', () {
      final topScores = List<Map<String, dynamic>>.from(_belgiumTopScoresOff);
      final snapshot = topScores.map((e) => Map<String, dynamic>.from(e)).toList();

      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: false,
        primaryScore: '1-0',
        primaryHome: 1,
        primaryAway: 0,
        primaryProb: 15.03,
        topScores: topScores,
        underdogScoresProbability: 53.22,
      ));

      buildUnderdogScoringNarrative(result);

      expect(result.topScores.map((s) => s.score).toList(),
          snapshot.map((e) => e['score']).toList());
      expect(result.topScores.map((s) => s.probability).toList(),
          snapshot.map((e) => (e['probability'] as num).toDouble()).toList());
    });

    test('does not change primary_predicted_score', () {
      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: false,
        primaryScore: '1-0',
        primaryHome: 1,
        primaryAway: 0,
        primaryProb: 15.03,
        topScores: _belgiumTopScoresOff,
        underdogScoresProbability: 53.22,
      ));

      final before = result.scorelineDecision!.primaryPredictedScore!;
      buildUnderdogScoringNarrative(result);
      final after = result.scorelineDecision!.primaryPredictedScore!;

      expect(after.homeGoals, before.homeGoals);
      expect(after.awayGoals, before.awayGoals);
      expect(after.probability, before.probability);
    });
  });

  group('UnderdogScoringNarrativeCard widget', () {
    Future<void> pumpCard(
      WidgetTester tester,
      PredictionResult result,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: Column(
                children: [
                  PredictionPrimaryScoreCard(
                    result: result,
                    isNeutralGround: true,
                  ),
                  UnderdogScoringNarrativeCard(
                    result: result,
                    isNeutralGround: true,
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    testWidgets('shows תחזית מרכזית and narrative labels', (tester) async {
      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: false,
        primaryScore: '1-0',
        primaryHome: 1,
        primaryAway: 0,
        primaryProb: 15.03,
        topScores: _belgiumTopScoresOff,
        underdogScoresProbability: 53.22,
        bttsProbability: 40.96,
      ));

      await pumpCard(tester, result);

      expect(find.text('תחזית מרכזית'), findsOneWidget);
      expect(find.textContaining('Belgium 1'), findsWidgets);
      expect(find.text('סיכוי שהאנדרדוג יבקיע'), findsOneWidget);
      expect(find.textContaining('Senegal: 53%'), findsOneWidget);
      expect(find.text('תרחיש ריאלי אם האנדרדוג כובש'), findsOneWidget);
      expect(find.textContaining('Belgium 2'), findsWidgets);
      expect(find.text('שתי הקבוצות כובשות'), findsOneWidget);
      expect(find.text('41%'), findsOneWidget);
    });

    testWidgets('hides narrative when underdog scores in primary', (tester) async {
      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: false,
        primaryScore: '2-1',
        primaryHome: 2,
        primaryAway: 1,
        primaryProb: 8.5,
        topScores: _belgiumTopScoresOff,
        underdogScoresProbability: 53.22,
      ));

      await pumpCard(tester, result);

      expect(find.text('תחזית מרכזית'), findsOneWidget);
      expect(find.text('סיכוי שהאנדרדוג יבקיע'), findsNothing);
    });

    testWidgets('NR3 decomposition UI still works alongside narrative',
        (tester) async {
      final result = PredictionResult.fromJson(_belgiumSenegalPayload(
        goliath: true,
        primaryScore: '2-0',
        primaryHome: 2,
        primaryAway: 0,
        primaryProb: 11.8,
        topScores: _belgiumTopScoresOn,
        underdogScoresProbability: 50.21,
      ));

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: Column(
                children: [
                  UnderdogScoringNarrativeCard(result: result),
                  ExpectedGoalsCard(result: result),
                ],
              ),
            ),
          ),
        ),
      );

      expect(find.text('סיכוי שהאנדרדוג יבקיע'), findsOneWidget);
      expect(find.text('פירוט חישוב NR3'), findsOneWidget);
    });

    testWidgets('legacy response without scoreline_decision does not crash',
        (tester) async {
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
        'probabilities_1x2': {
          'home_win': 40.0,
          'draw': 30.0,
          'away_win': 30.0,
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

      expect(find.text('סיכוי שהאנדרדוג יבקיע'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  group('validation fixtures', () {
    test('parsed prediction values are stable after narrative helpers', () {
      final payloads = [
        _belgiumSenegalPayload(
          goliath: false,
          primaryScore: '1-0',
          primaryHome: 1,
          primaryAway: 0,
          primaryProb: 15.03,
          topScores: _belgiumTopScoresOff,
          underdogScoresProbability: 53.22,
          bttsProbability: 40.96,
        ),
        _belgiumSenegalPayload(
          goliath: true,
          primaryScore: '2-0',
          primaryHome: 2,
          primaryAway: 0,
          primaryProb: 11.8,
          topScores: _belgiumTopScoresOn,
          underdogScoresProbability: 50.21,
        ),
      ];

      for (final payload in payloads) {
        final before = PredictionResult.fromJson(payload);
        final snapshot = _predictionValueSnapshot(before);

        buildUnderdogScoringNarrative(before);
        shouldShowUnderdogScoringNarrative(before);

        final after = PredictionResult.fromJson(payload);
        expect(_predictionValueSnapshot(after), snapshot);
      }
    });
  });
}

Map<String, dynamic> _predictionValueSnapshot(PredictionResult r) {
  final primary = r.scorelineDecision?.primaryPredictedScore;
  return {
    'home_xg': r.homeXg,
    'away_xg': r.awayXg,
    'probabilities_1x2': {
      'home_win': r.probabilities.homeWin,
      'draw': r.probabilities.draw,
      'away_win': r.probabilities.awayWin,
    },
    'primary': primary == null
        ? null
        : {
            'home': primary.homeGoals,
            'away': primary.awayGoals,
            'prob': primary.probability,
          },
    'top_scores': r.topScores
        .map((s) => {'score': s.score, 'prob': s.probability})
        .toList(),
  };
}
