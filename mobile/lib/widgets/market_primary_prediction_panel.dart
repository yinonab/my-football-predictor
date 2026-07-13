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
        _MarketDirectionCard(block: block, theme: theme),
        const SizedBox(height: 12),
        _GoalSignalsCard(block: block, theme: theme),
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
            Text(
              block.selectedScore ?? '—',
              textAlign: TextAlign.center,
              style: theme.textTheme.displaySmall?.copyWith(
                fontWeight: FontWeight.bold,
                color: theme.colorScheme.primary,
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
  final ThemeData theme;

  const _MarketDirectionCard({required this.block, required this.theme});

  @override
  Widget build(BuildContext context) {
    final h2h = block.inputs.h2h;
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
            _PctRow(label: 'בית', value: h2h.home),
            _PctRow(label: 'תיקו', value: h2h.draw),
            _PctRow(label: 'חוץ', value: h2h.away),
          ],
        ),
      ),
    );
  }
}

class _GoalSignalsCard extends StatelessWidget {
  final MarketPrimaryPrediction block;
  final ThemeData theme;

  const _GoalSignalsCard({required this.block, required this.theme});

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
            _SignalRow(
              label: 'מעל/מתחת 2.5',
              value: _goalTrendLabel(block.marketGoalTrend),
            ),
            _SignalRow(label: 'BTTS', value: _bttsLabel(block.bttsSignal)),
            _SignalRow(
              label: 'האנדיקפ',
              value: _spreadLabel(block.spreadSignal),
            ),
          ],
        ),
      ),
    );
  }

  static String _goalTrendLabel(String? trend) {
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

  static String _bttsLabel(String? signal) {
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

  static String _spreadLabel(String? signal) {
    if (signal == null || signal == 'unavailable') return 'לא זמין';
    if (signal == 'neutral') return 'ניטרלי';
    return signal.replaceAll('_', ' ');
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
              return Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(
                  children: [
                    Expanded(
                      flex: 3,
                      child: LinearProgressIndicator(
                        value: frac,
                        backgroundColor: theme.colorScheme.surfaceContainerHighest,
                        color: highlight
                            ? theme.colorScheme.primary
                            : theme.colorScheme.secondary,
                      ),
                    ),
                    const SizedBox(width: 8),
                    SizedBox(
                      width: 72,
                      child: Text(
                        '${row.score}  ${row.probability.toStringAsFixed(1)}%',
                        textAlign: TextAlign.left,
                        style: highlight
                            ? theme.textTheme.bodyMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                              )
                            : theme.textTheme.bodyMedium,
                      ),
                    ),
                  ],
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

class _PctRow extends StatelessWidget {
  final String label;
  final double? value;

  const _PctRow({required this.label, this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(value != null ? '${value!.toStringAsFixed(1)}%' : '—'),
          Text(label),
        ],
      ),
    );
  }
}

class _SignalRow extends StatelessWidget {
  final String label;
  final String value;

  const _SignalRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(value),
          Text(label),
        ],
      ),
    );
  }
}
