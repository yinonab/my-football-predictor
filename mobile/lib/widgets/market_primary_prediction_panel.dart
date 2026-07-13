import 'package:flutter/material.dart';

import '../models/prediction_result.dart';

Color qualityBandColor(String band) {
  switch (band.toUpperCase()) {
    case 'GREEN':
      return Colors.green.shade700;
    case 'YELLOW':
      return Colors.amber.shade800;
    case 'RED':
      return Colors.red.shade700;
    default:
      return Colors.blueGrey;
  }
}

String primaryTeamLabel(String full) {
  final idx = full.indexOf('(');
  if (idx > 0) return full.substring(0, idx).trim();
  return full.trim();
}

String marketGoalTrendLabel(String? trend) {
  switch (trend) {
    case 'under_2_5':
      return 'מתחת 2.5';
    case 'over_2_5':
      return 'מעל 2.5';
    case 'neutral':
      return 'ניטרלי';
    default:
      return 'לא זמין';
  }
}

String bttsSignalLabel(String? signal) {
  switch (signal) {
    case 'yes':
      return 'כן';
    case 'no':
      return 'לא';
    case 'neutral':
      return 'ניטרלי';
    default:
      return 'לא זמין';
  }
}

String spreadSignalLabel({
  required String? signal,
  String? homeTeam,
  String? awayTeam,
}) {
  if (signal == null || signal == 'unavailable') return 'לא זמין';
  if (signal == 'neutral') return 'ניטרלי';

  final home = homeTeam != null ? primaryTeamLabel(homeTeam) : null;
  final away = awayTeam != null ? primaryTeamLabel(awayTeam) : null;

  switch (signal) {
    case 'slight_home_favorite':
      return home != null ? '$home פייבוריטית קלה' : 'פייבוריט ביתי קל';
    case 'clear_home_favorite':
      return home != null ? '$home פייבוריטית ברורה' : 'פייבוריט ביתי ברור';
    case 'strong_home_favorite':
      return home != null ? '$home פייבוריטית חזקה' : 'פייבוריט ביתי חזק';
    case 'slight_away_favorite':
      return away != null ? '$away פייבוריטית קלה' : 'פייבוריט חוץ קל';
    case 'clear_away_favorite':
      return away != null ? '$away פייבוריטית ברורה' : 'פייבוריט חוץ ברור';
    case 'strong_away_favorite':
      return away != null ? '$away פייבוריטית חזקה' : 'פייבוריט חוץ חזק';
    default:
      return 'לא זמין';
  }
}

/// Interpreted market-primary prediction tab (תחזית שוק).
class MarketPrimaryPredictionPanel extends StatelessWidget {
  final PredictionResult result;

  const MarketPrimaryPredictionPanel({super.key, required this.result});

  static bool shouldShow(PredictionResult result) =>
      result.marketPrimaryPrediction != null;

  @override
  Widget build(BuildContext context) {
    final block = result.marketPrimaryPrediction;
    if (block == null) {
      return const _UnavailableCard();
    }
    if (!block.applied) {
      return _FallbackCard(reason: block.reason);
    }
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _HeroCard(block: block, theme: theme),
        const SizedBox(height: 12),
        _MarketDirectionCard(
          block: block,
          homeTeam: result.homeTeam,
          awayTeam: result.awayTeam,
          theme: theme,
        ),
        const SizedBox(height: 12),
        _GoalSignalsCard(
          block: block,
          homeTeam: result.homeTeam,
          awayTeam: result.awayTeam,
          theme: theme,
        ),
        const SizedBox(height: 12),
        if (block.explanation != null && block.explanation!.isNotEmpty)
          _ExplanationCard(text: block.explanation!),
        if (block.topScores.isNotEmpty) ...[
          const SizedBox(height: 12),
          _TopScoresCard(
            scores: block.topScores,
            selected: block.selectedScore,
            theme: theme,
          ),
        ],
        const SizedBox(height: 12),
        _InputsCard(block: block, theme: theme),
      ],
    );
  }
}

class _UnavailableCard extends StatelessWidget {
  const _UnavailableCard();

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Text(
          'תחזית שוק אינה זמינה למשחק זה',
          textAlign: TextAlign.right,
          style: Theme.of(context).textTheme.bodyLarge,
        ),
      ),
    );
  }
}

class _FallbackCard extends StatelessWidget {
  final String reason;

  const _FallbackCard({required this.reason});

  @override
  Widget build(BuildContext context) {
    final label = _reasonHebrew(reason);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'תחזית שוק אינה זמינה למשחק זה',
              textAlign: TextAlign.right,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Text(
              label,
              textAlign: TextAlign.right,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ],
        ),
      ),
    );
  }

  static String _reasonHebrew(String reason) {
    switch (reason) {
      case 'quality_below_minimum':
        return 'איכות נתוני השוק נמוכה מדי לתחזית שוק.';
      case 'market_unavailable':
        return 'נתוני שוק לא זמינים.';
      case 'missing_h2h':
        return 'חסרים נתוני 1X2 מהשוק.';
      case 'provider_disabled':
        return 'שירות השוק אינו פעיל.';
      default:
        return reason;
    }
  }
}

class _HeroCard extends StatelessWidget {
  final MarketPrimaryPrediction block;
  final ThemeData theme;

  const _HeroCard({required this.block, required this.theme});

  @override
  Widget build(BuildContext context) {
    final band = block.confidence ?? '';
    final bandColor = qualityBandColor(band);
    return Card(
      elevation: 2,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'תחזית שוק',
              textAlign: TextAlign.right,
              style: theme.textTheme.titleLarge?.copyWith(
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 12),
            Directionality(
              textDirection: TextDirection.ltr,
              child: Text(
                block.selectedScore ?? '—',
                textAlign: TextAlign.center,
                style: theme.textTheme.displaySmall?.copyWith(
                  fontWeight: FontWeight.bold,
                  color: theme.colorScheme.primary,
                ),
              ),
            ),
            const SizedBox(height: 4),
            Text(
              'תוצאה מומלצת לפי שוק',
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium,
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              alignment: WrapAlignment.end,
              children: [
                if (band.isNotEmpty)
                  Chip(
                    label: Text(band),
                    backgroundColor: bandColor.withValues(alpha: 0.15),
                    labelStyle: TextStyle(color: bandColor),
                  ),
                if (block.marketWeightPct != null && block.modelWeightPct != null)
                  Chip(
                    label: Text(
                      '${block.marketWeightPct}% שוק / ${block.modelWeightPct}% מודל',
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MarketDirectionCard extends StatelessWidget {
  final MarketPrimaryPrediction block;
  final String homeTeam;
  final String awayTeam;
  final ThemeData theme;

  const _MarketDirectionCard({
    required this.block,
    required this.homeTeam,
    required this.awayTeam,
    required this.theme,
  });

  @override
  Widget build(BuildContext context) {
    final h2h = block.inputs.h2h;
    final homeLabel = primaryTeamLabel(homeTeam);
    final awayLabel = primaryTeamLabel(awayTeam);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'כיוון השוק',
              textAlign: TextAlign.right,
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            if (block.marketFavorite != null)
              Text(
                'מועדף שוק: ${block.marketFavorite}',
                textAlign: TextAlign.right,
              ),
            const SizedBox(height: 8),
            _LabelValueRow(label: homeLabel, value: _pct(h2h.home)),
            _LabelValueRow(label: 'תיקו', value: _pct(h2h.draw)),
            _LabelValueRow(label: awayLabel, value: _pct(h2h.away)),
          ],
        ),
      ),
    );
  }

  static String _pct(double? value) =>
      value != null ? '${value.toStringAsFixed(1)}%' : '—';
}

class _GoalSignalsCard extends StatelessWidget {
  final MarketPrimaryPrediction block;
  final String homeTeam;
  final String awayTeam;
  final ThemeData theme;

  const _GoalSignalsCard({
    required this.block,
    required this.homeTeam,
    required this.awayTeam,
    required this.theme,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'אותות שערים',
              textAlign: TextAlign.right,
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            _LabelValueRow(
              label: 'מעל/מתחת 2.5',
              value: marketGoalTrendLabel(block.marketGoalTrend),
            ),
            _LabelValueRow(
              label: 'BTTS',
              value: bttsSignalLabel(block.bttsSignal),
            ),
            _LabelValueRow(
              label: 'האנדיקפ',
              value: spreadSignalLabel(
                signal: block.spreadSignal,
                homeTeam: homeTeam,
                awayTeam: awayTeam,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ExplanationCard extends StatelessWidget {
  final String text;

  const _ExplanationCard({required this.text});

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'הסבר',
              textAlign: TextAlign.right,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            Directionality(
              textDirection: TextDirection.ltr,
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  text,
                  textAlign: TextAlign.left,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _TopScoresCard extends StatelessWidget {
  final List<MarketPrimaryPredictionScore> scores;
  final String? selected;
  final ThemeData theme;

  const _TopScoresCard({
    required this.scores,
    required this.selected,
    required this.theme,
  });

  @override
  Widget build(BuildContext context) {
    final maxProb = scores
        .map((s) => s.probability)
        .fold<double>(0, (a, b) => a > b ? a : b);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'תוצאות מובילות לפי שוק',
              textAlign: TextAlign.right,
              style: theme.textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            ...scores.map((row) {
              final highlight = row.score == selected;
              final frac = maxProb > 0 ? row.probability / maxProb : 0.0;
              final textStyle = highlight
                  ? theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                    )
                  : theme.textTheme.bodyMedium;
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Directionality(
                  textDirection: TextDirection.ltr,
                  child: Row(
                    children: [
                      SizedBox(
                        width: 40,
                        child: Text(
                          row.score,
                          style: textStyle,
                        ),
                      ),
                      SizedBox(
                        width: 56,
                        child: Text(
                          '${row.probability.toStringAsFixed(1)}%',
                          style: textStyle,
                        ),
                      ),
                      Expanded(
                        child: LinearProgressIndicator(
                          value: frac,
                          backgroundColor:
                              theme.colorScheme.surfaceContainerHighest,
                          color: highlight
                              ? theme.colorScheme.primary
                              : theme.colorScheme.secondary,
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }),
          ],
        ),
      ),
    );
  }
}

class _InputsCard extends StatelessWidget {
  final MarketPrimaryPrediction block;
  final ThemeData theme;

  const _InputsCard({required this.block, required this.theme});

  @override
  Widget build(BuildContext context) {
    final totals = block.inputs.totals;
    final btts = block.inputs.btts;
    return ExpansionTile(
      title: Text(
        'קלט ואבחון',
        textAlign: TextAlign.right,
        style: theme.textTheme.titleSmall,
      ),
      children: [
        if (totals.line != null)
          ListTile(
            title: Text(
              'קו O/U: ${totals.line} | מעל ${totals.over?.toStringAsFixed(1) ?? "—"}% | מתחת ${totals.under?.toStringAsFixed(1) ?? "—"}%',
              textAlign: TextAlign.right,
            ),
          ),
        if (btts.yes != null)
          ListTile(
            title: Text(
              'BTTS: כן ${btts.yes!.toStringAsFixed(1)}% | לא ${btts.no?.toStringAsFixed(1) ?? "—"}%',
              textAlign: TextAlign.right,
            ),
          ),
        if (block.inputs.spread != null)
          ListTile(
            title: Text(
              'האנדיקפ: ${block.inputs.spread}',
              textAlign: TextAlign.right,
            ),
          ),
        if (block.notes.isNotEmpty)
          ...block.notes.map(
            (n) => ListTile(
              dense: true,
              title: Text(n, textAlign: TextAlign.right),
            ),
          ),
      ],
    );
  }
}

class _LabelValueRow extends StatelessWidget {
  final String label;
  final String value;

  const _LabelValueRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              textAlign: TextAlign.right,
            ),
          ),
          const SizedBox(width: 12),
          Directionality(
            textDirection: TextDirection.ltr,
            child: Text(
              value,
              textAlign: TextAlign.left,
            ),
          ),
        ],
      ),
    );
  }
}
