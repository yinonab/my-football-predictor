import 'market_diagnostics.dart';
import 'prediction_result.dart';

/// View-model for the market tab — merges current + future API shapes.
class MarketTabViewModel {
  final bool marketDataAvailable;
  final String statusMessage;
  final Map<String, double> modelProbabilities1x2;
  final Map<String, double> displayProbabilities1x2;
  final Map<String, double>? marketConsensus1x2;
  final List<BookmakerQuote> bookmakers;
  final bool oddsAffectPrediction;
  final bool oddsBlendApplied;
  final String? primarySource;
  final String blendModeLabel;
  final double? modelWeightPercent;
  final double? marketWeightPercent;
  final List<String> notes;

  const MarketTabViewModel({
    required this.marketDataAvailable,
    required this.statusMessage,
    required this.modelProbabilities1x2,
    required this.displayProbabilities1x2,
    this.marketConsensus1x2,
    this.bookmakers = const [],
    this.oddsAffectPrediction = false,
    this.oddsBlendApplied = false,
    this.primarySource,
    this.blendModeLabel = 'תצוגה בלבד',
    this.modelWeightPercent,
    this.marketWeightPercent,
    this.notes = const [],
  });

  static MarketTabViewModel fromPredictionResult(PredictionResult result) {
    final prob = result.probabilityDiagnostics;
    final marketPayload = result.marketDiagnostics;

    Map<String, double>? marketMap;
    List<BookmakerQuote> quotes = List.of(marketPayload?.bookmakers ?? []);

    if (marketPayload?.consensus1x2Percent != null &&
        marketPayload!.consensus1x2Percent!.isNotEmpty) {
      marketMap = Map.of(marketPayload.consensus1x2Percent!);
    } else if (prob?.marketProbabilities1x2 != null &&
        prob!.marketProbabilities1x2!.isNotEmpty) {
      marketMap = Map.of(prob.marketProbabilities1x2!);
    }

    if (marketMap != null && quotes.isEmpty) {
      quotes = [
        BookmakerQuote(
          id: 'consensus',
          displayName:
              prob?.oddsSource ?? marketPayload?.primarySource ?? 'ממוצע שוק',
          implied1x2Percent: marketMap,
          sourceKey: 'the_odds_api',
          isConsensus: true,
        ),
      ];
    }

    final available = marketMap != null && marketMap.isNotEmpty;
    final notes = <String>[
      ...?marketPayload?.notes,
      if (marketPayload?.status == 'quota_exceeded')
        'מכסת The Odds API נגמרה לחודש — בדוק בלוח הבקרה של הספק או המתן לאיפוס.',
      if (marketPayload != null &&
          marketPayload.oddsKeyConfigured &&
          !available &&
          marketPayload.status == 'no_odds_for_matchup')
        'השרת מחובר לשוק אך אין יחסים לזוג הנבחרות הזה כרגע.',
      if (marketPayload != null &&
          !marketPayload.oddsKeyConfigured &&
          marketPayload.status == 'not_configured')
        'מפתח שוק לא מוגדר בשרת (THE_ODDS_API_KEY).',
      if (!result.oddsAffectPrediction)
        'שקלול שוק בחיזוי כבוי — מוצגים מודל ושוק זה לצד זה.',
    ];

    final modelRaw = prob?.rawProbabilities1x2;
    final modelForCompare = (modelRaw != null && modelRaw.isNotEmpty)
        ? modelRaw
        : _probsFrom1x2(result.probabilities);

    final keyConfigured = marketPayload?.oddsKeyConfigured ?? false;
    String status;
    if (available) {
      status = 'זמין';
    } else if (marketPayload?.status == 'quota_exceeded') {
      status = 'מכסה נגמרה';
    } else if (keyConfigured) {
      status = 'אין יחסים למשחק';
    } else {
      status = 'לא מחובר';
    }

    String blendLabel = 'תצוגה בלבד — ללא שקלול בחיזוי';
    if (result.oddsAffectPrediction && result.oddsBlendApplied) {
      blendLabel = 'שקלול פעיל בחיזוי';
    } else if (marketPayload != null && marketPayload.blendMode.isNotEmpty) {
      blendLabel = marketPayload.blendMode;
    }

    return MarketTabViewModel(
      marketDataAvailable: available,
      statusMessage: status,
      modelProbabilities1x2: modelForCompare,
      displayProbabilities1x2: _probsFrom1x2(result.probabilities),
      marketConsensus1x2: marketMap,
      bookmakers: quotes,
      oddsAffectPrediction: result.oddsAffectPrediction,
      oddsBlendApplied: result.oddsBlendApplied,
      primarySource: marketPayload?.primarySource ?? prob?.oddsSource,
      blendModeLabel: blendLabel,
      modelWeightPercent: prob?.oddsBlendWeightModel != null
          ? prob!.oddsBlendWeightModel! * 100
          : 70,
      marketWeightPercent: prob?.oddsBlendWeightMarket != null
          ? prob!.oddsBlendWeightMarket! * 100
          : 30,
      notes: notes,
    );
  }

  static Map<String, double> _probsFrom1x2(Probabilities1X2 p) {
    return {
      'home_win': p.homeWin,
      'draw': p.draw,
      'away_win': p.awayWin,
    };
  }
}
