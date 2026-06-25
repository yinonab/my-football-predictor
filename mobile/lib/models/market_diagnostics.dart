/// Single bookmaker line — populated from API now or from future multi-source backend.
class BookmakerQuote {
  final String id;
  final String displayName;
  final String region;
  final double? homeDecimalOdds;
  final double? drawDecimalOdds;
  final double? awayDecimalOdds;
  final Map<String, double> implied1x2Percent;
  final String sourceKey;
  final bool isConsensus;

  const BookmakerQuote({
    required this.id,
    required this.displayName,
    this.region = '',
    this.homeDecimalOdds,
    this.drawDecimalOdds,
    this.awayDecimalOdds,
    this.implied1x2Percent = const {},
    this.sourceKey = 'unknown',
    this.isConsensus = false,
  });

  factory BookmakerQuote.fromJson(Map<String, dynamic> json) {
    final impliedRaw = json['implied_1x2_percent'] as Map<String, dynamic>? ??
        json['implied_1x2'] as Map<String, dynamic>?;
    final implied = <String, double>{};
    if (impliedRaw != null) {
      for (final entry in impliedRaw.entries) {
        implied[entry.key] = (entry.value as num).toDouble();
      }
    }
    return BookmakerQuote(
      id: json['id'] as String? ?? json['bookmaker_id'] as String? ?? '',
      displayName:
          json['display_name'] as String? ?? json['bookmaker'] as String? ?? '',
      region: json['region'] as String? ?? '',
      homeDecimalOdds: (json['home_decimal_odds'] as num?)?.toDouble(),
      drawDecimalOdds: (json['draw_decimal_odds'] as num?)?.toDouble(),
      awayDecimalOdds: (json['away_decimal_odds'] as num?)?.toDouble(),
      implied1x2Percent: implied,
      sourceKey: json['source_key'] as String? ?? 'unknown',
      isConsensus: json['is_consensus'] as bool? ?? false,
    );
  }
}

/// Extended market block — optional until backend Phase B ships.
class MarketDiagnosticsPayload {
  final bool available;
  final String status;
  final String? primarySource;
  final String? fetchedAtUtc;
  final List<BookmakerQuote> bookmakers;
  final Map<String, double>? consensus1x2Percent;
  final String blendMode;
  final bool oddsKeyConfigured;
  final int? requestsRemaining;
  final List<String> notes;

  const MarketDiagnosticsPayload({
    this.available = false,
    this.status = 'unavailable',
    this.primarySource,
    this.fetchedAtUtc,
    this.bookmakers = const [],
    this.consensus1x2Percent,
    this.blendMode = 'diagnostic_only',
    this.oddsKeyConfigured = false,
    this.requestsRemaining,
    this.notes = const [],
  });

  factory MarketDiagnosticsPayload.fromJson(Map<String, dynamic> json) {
    final quotes = (json['bookmakers'] as List<dynamic>? ?? [])
        .map((e) => BookmakerQuote.fromJson(e as Map<String, dynamic>))
        .toList();
    final consensusRaw =
        json['consensus_1x2_percent'] as Map<String, dynamic>?;
    Map<String, double>? consensus;
    if (consensusRaw != null) {
      consensus = consensusRaw.map(
        (k, v) => MapEntry(k, (v as num).toDouble()),
      );
    }
    return MarketDiagnosticsPayload(
      available: json['available'] as bool? ?? false,
      status: json['status'] as String? ?? 'unavailable',
      primarySource: json['primary_source'] as String?,
      fetchedAtUtc: json['fetched_at_utc'] as String?,
      bookmakers: quotes,
      consensus1x2Percent: consensus,
      blendMode: json['blend_mode'] as String? ?? 'diagnostic_only',
      oddsKeyConfigured: json['odds_key_configured'] as bool? ?? false,
      requestsRemaining: (json['requests_remaining'] as num?)?.toInt(),
      notes: List<String>.from(json['notes'] as List<dynamic>? ?? []),
    );
  }
}

class ProbabilityDiagnostics {
  final double probabilitySum;
  final bool probabilitySumValid;
  final bool oddsAvailable;
  final bool oddsAffectPrediction;
  final bool oddsBlendApplied;
  final Map<String, double> rawProbabilities1x2;
  final Map<String, double> finalProbabilities1x2;
  final Map<String, double>? marketProbabilities1x2;
  final String? oddsSource;
  final double? oddsBlendWeightModel;
  final double? oddsBlendWeightMarket;
  final List<String> coherenceWarnings;

  const ProbabilityDiagnostics({
    required this.probabilitySum,
    required this.probabilitySumValid,
    this.oddsAvailable = false,
    this.oddsAffectPrediction = false,
    this.oddsBlendApplied = false,
    required this.rawProbabilities1x2,
    required this.finalProbabilities1x2,
    this.marketProbabilities1x2,
    this.oddsSource,
    this.oddsBlendWeightModel,
    this.oddsBlendWeightMarket,
    this.coherenceWarnings = const [],
  });

  factory ProbabilityDiagnostics.fromJson(Map<String, dynamic> json) {
    Map<String, double> parseProbs(Map<String, dynamic>? raw) {
      if (raw == null) return {};
      return raw.map((k, v) => MapEntry(k, (v as num).toDouble()));
    }

    return ProbabilityDiagnostics(
      probabilitySum: (json['probability_sum'] as num?)?.toDouble() ?? 0,
      probabilitySumValid: json['probability_sum_valid'] as bool? ?? true,
      oddsAvailable: json['odds_available'] as bool? ?? false,
      oddsAffectPrediction: json['odds_affect_prediction'] as bool? ?? false,
      oddsBlendApplied: json['odds_blend_applied'] as bool? ?? false,
      rawProbabilities1x2:
          parseProbs(json['raw_probabilities_1x2'] as Map<String, dynamic>?),
      finalProbabilities1x2: parseProbs(
        json['final_probabilities_1x2'] as Map<String, dynamic>?,
      ),
      marketProbabilities1x2: json['market_probabilities_1x2'] != null
          ? parseProbs(
              json['market_probabilities_1x2'] as Map<String, dynamic>,
            )
          : null,
      oddsSource: json['odds_source'] as String?,
      oddsBlendWeightModel:
          (json['odds_blend_weight_model'] as num?)?.toDouble(),
      oddsBlendWeightMarket:
          (json['odds_blend_weight_market'] as num?)?.toDouble(),
      coherenceWarnings: List<String>.from(
        json['coherence_warnings'] as List<dynamic>? ?? [],
      ),
    );
  }
}
