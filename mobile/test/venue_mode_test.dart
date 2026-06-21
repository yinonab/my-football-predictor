import 'package:flutter_test/flutter_test.dart';
import 'package:football_predictor/models/prediction_result.dart';
import 'package:football_predictor/models/venue_mode.dart';
import 'package:football_predictor/utils/prediction_ui_copy.dart';

void main() {
  group('buildPredictRequestBody', () {
    test('sends venue_mode=neutral', () {
      final body = buildPredictRequestBody(
        homeTeam: 'United States (ארצות הברית)',
        awayTeam: 'Australia (אוסטרליה)',
        venueMode: VenueMode.neutral,
        rho: -0.15,
        avgGoals: 2.6,
        homeAdvantage: 0,
        alpha: 0,
        altitude: 0,
        starAbsent: false,
        awayStarAbsent: false,
        useLiveStats: false,
      );

      expect(body['venue_mode'], 'neutral');
      expect(body['neutral_ground'], isTrue);
    });

    test('sends venue_mode=first_team_home', () {
      final body = buildPredictRequestBody(
        homeTeam: 'A',
        awayTeam: 'B',
        venueMode: VenueMode.firstTeamHome,
        rho: -0.15,
        avgGoals: 2.6,
        homeAdvantage: 0,
        alpha: 0,
        altitude: 0,
        starAbsent: false,
        awayStarAbsent: false,
        useLiveStats: false,
      );

      expect(body['venue_mode'], 'first_team_home');
      expect(body['neutral_ground'], isFalse);
    });

    test('sends venue_mode=second_team_home', () {
      final body = buildPredictRequestBody(
        homeTeam: 'A',
        awayTeam: 'B',
        venueMode: VenueMode.secondTeamHome,
        rho: -0.15,
        avgGoals: 2.6,
        homeAdvantage: 0,
        alpha: 0,
        altitude: 0,
        starAbsent: false,
        awayStarAbsent: false,
        useLiveStats: false,
      );

      expect(body['venue_mode'], 'second_team_home');
      expect(body['neutral_ground'], isFalse);
    });

    test('sends venue_mode=host_country_auto', () {
      final body = buildPredictRequestBody(
        homeTeam: 'A',
        awayTeam: 'B',
        venueMode: VenueMode.hostCountryAuto,
        rho: -0.15,
        avgGoals: 2.6,
        homeAdvantage: 0,
        alpha: 0,
        altitude: 0,
        starAbsent: false,
        awayStarAbsent: false,
        useLiveStats: false,
      );

      expect(body['venue_mode'], 'host_country_auto');
      expect(body['neutral_ground'], isFalse);
    });
  });

  group('venue context copy', () {
    const home = 'United States (ארצות הברית)';
    const away = 'Australia (אוסטרליה)';

    test('neutral summary', () {
      final line = venueContextSummaryLine(
        diag: const MatchContextDiagnostics(
          venueMode: 'neutral',
          hostAdvantageApplied: false,
        ),
        homeTeam: home,
        awayTeam: away,
      );
      expect(line, contains('מגרש ניטרלי'));
      expect(line, contains('אין יתרון ביתיות'));
    });

    test('first_team_home applied', () {
      final line = venueContextSummaryLine(
        diag: const MatchContextDiagnostics(
          venueMode: 'first_team_home',
          hostAdvantageApplied: true,
          homeAdvantagePowerDelta: 35,
        ),
        homeTeam: home,
        awayTeam: away,
      );
      expect(line, contains('ארצות הברית'));
      expect(line, contains('נוסף יתרון ביתיות'));
    });

    test('second_team_home applied', () {
      final line = venueContextSummaryLine(
        diag: const MatchContextDiagnostics(
          venueMode: 'second_team_home',
          hostAdvantageApplied: true,
          homeAdvantageTeam: 'away',
        ),
        homeTeam: home,
        awayTeam: away,
      );
      expect(line, contains('אוסטרליה'));
      expect(line, contains('נוסף יתרון ביתיות'));
    });

    test('host_country_auto unavailable', () {
      final line = venueContextSummaryLine(
        diag: const MatchContextDiagnostics(
          venueMode: 'host_country_auto',
          hostAdvantageApplied: false,
        ),
        homeTeam: home,
        awayTeam: away,
      );
      expect(line, contains('לא זוהתה מדינה מארחת'));
      expect(line, contains('אין יתרון ביתיות'));
    });

    test('fallback when backend omits venue_mode', () {
      final mode = effectiveVenueModeApi(
        const MatchContextDiagnostics(neutralGroundRequested: false),
        VenueMode.firstTeamHome,
      );
      expect(mode, 'first_team_home');

      final line = venueContextSummaryLine(
        diag: const MatchContextDiagnostics(
          hostAdvantageApplied: true,
          homeAdvantagePowerDelta: 35,
        ),
        homeTeam: home,
        awayTeam: away,
        requestedVenueMode: VenueMode.firstTeamHome,
      );
      expect(line, contains('ארצות הברית'));
    });
  });

  group('home advantage explanation', () {
    test('applied says included in calculation', () {
      expect(
        homeAdvantageExplanation(
          diag: const MatchContextDiagnostics(
            venueMode: 'first_team_home',
            hostAdvantageApplied: true,
          ),
          requestedVenueMode: VenueMode.firstTeamHome,
        ),
        'יתרון ביתיות נכלל בחישוב.',
      );
    });

    test('neutral not applied', () {
      expect(
        homeAdvantageExplanation(
          diag: const MatchContextDiagnostics(
            venueMode: 'neutral',
            hostAdvantageApplied: false,
          ),
          requestedVenueMode: VenueMode.neutral,
        ),
        'מגרש ניטרלי — אין יתרון ביתיות.',
      );
    });

    test('power delta line', () {
      expect(
        homeAdvantagePowerDeltaLine(
          const MatchContextDiagnostics(
            hostAdvantageApplied: true,
            homeAdvantagePowerDelta: 35,
          ),
        ),
        'השפעת ביתיות: +35 נקודות כוח',
      );
    });
  });
}
