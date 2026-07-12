import 'package:flutter/material.dart';

import '../models/prediction_result.dart';
import '../utils/market_ui_copy.dart';

/// Market Influence dashboard shown on the Market tab when influence is applied.
class MarketInfluenceSection extends StatelessWidget {
  final PredictionResult result;

  const MarketInfluenceSection({super.key, required this.result});

  static bool shouldShow(PredictionResult result) =>
      result.marketInfluence?.marketInfluenceApplied == true;

  @override
  Widget build(BuildContext context) {
    final influence = result.marketInfluence!;
    final explanation = influence.explanation;
    final theme = Theme.of(context);
    final bandStyle = _qualityBandStyle(theme, influence.qualityBand);
    final selectedScore = _selectedScore(result, explanation);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _HeroCard(
          title: explanation?.title,
          selectedScore: selectedScore,
          selectedScoreLabel: explanation?.selectedScoreLabel,
          summary: explanation?.summary,
          signalLabel: explanation?.signalLabel,
          qualityBand: influence.qualityBand,
          influenceLabel: explanation?.influenceLabel,
          influenceWeightPct: influence.influenceWeightPct,
          bandStyle: bandStyle,
        ),
        const SizedBox(height: 12),
        if (explanation != null && explanation.details.isNotEmpty)
          _ExplanationDetailsCard(details: explanation.details),
        if (result.topScores.isNotEmpty) ...[
          const SizedBox(height: 12),
          _TopScoresCard(
            scores: result.topScores.take(5).toList(),
            accent: bandStyle.accent,
          ),
        ],
        const SizedBox(height: 12),
        _TechnicalMarketDetails(
          influence: influence,
          primaryScoreReason: result.scorelineDecision?.primaryScoreReason,
        ),
        const SizedBox(height: 12),
        _FooterNote(theme: theme),
      ],
    );
  }

  static String? _selectedScore(
    PredictionResult result,
    MarketInfluenceExplanation? explanation,
  ) {
    final primary = result.scorelineDecision?.primaryPredictedScore;
    if (primary != null) {
      return '${primary.homeGoals}-${primary.awayGoals}';
    }
    final label = explanation?.selectedScoreLabel ?? '';
    final match = RegExp(r'(\d+-\d+)').firstMatch(label);
    return match?.group(1);
  }
}

class _BandStyle {
  final Color accent;
  final Color chipBackground;
  final Color chipForeground;

  const _BandStyle({
    required this.accent,
    required this.chipBackground,
    required this.chipForeground,
  });
}

_BandStyle _qualityBandStyle(ThemeData theme, String? band) {
  final normalized = (band ?? '').toUpperCase();
  if (normalized == 'YELLOW') {
    return _BandStyle(
      accent: Colors.amber.shade700,
      chipBackground: Colors.amber.shade100.withValues(
        alpha: theme.brightness == Brightness.dark ? 0.25 : 1.0,
      ),
      chipForeground: Colors.amber.shade900,
    );
  }
  if (normalized == 'RED') {
    return _BandStyle(
      accent: theme.colorScheme.outline,
      chipBackground: theme.colorScheme.surfaceContainerHighest,
      chipForeground: theme.colorScheme.onSurfaceVariant,
    );
  }
  return _BandStyle(
    accent: theme.colorScheme.primary,
    chipBackground: theme.colorScheme.primaryContainer,
    chipForeground: theme.colorScheme.onPrimaryContainer,
  );
}

class _HeroCard extends StatelessWidget {
  final String? title;
  final String? selectedScore;
  final String? selectedScoreLabel;
  final String? summary;
  final String? signalLabel;
  final String? qualityBand;
  final String? influenceLabel;
  final int? influenceWeightPct;
  final _BandStyle bandStyle;

  const _HeroCard({
    required this.title,
    required this.selectedScore,
    required this.selectedScoreLabel,
    required this.summary,
    required this.signalLabel,
    required this.qualityBand,
    required this.influenceLabel,
    required this.influenceWeightPct,
    required this.bandStyle,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final weightLabel = influenceLabel?.trim().isNotEmpty == true
        ? influenceLabel!
        : (influenceWeightPct != null ? '$influenceWeightPct% market influence' : '');

    return Card(
      elevation: 0,
      color: theme.colorScheme.primaryContainer.withValues(alpha: 0.35),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: bandStyle.accent.withValues(alpha: 0.35)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (title != null && title!.isNotEmpty) ...[
              Row(
                children: [
                  Icon(Icons.insights_outlined, color: bandStyle.accent, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      title!,
                      style: theme.textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                      textAlign: TextAlign.right,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
            ],
            if (selectedScore != null) ...[
              Text(
                'תוצאה נבחרת',
                style: theme.textTheme.labelLarge?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 4),
              Directionality(
                textDirection: TextDirection.ltr,
                child: Text(
                  selectedScore!,
                  style: theme.textTheme.displaySmall?.copyWith(
                    fontWeight: FontWeight.w800,
                    letterSpacing: 2,
                    color: bandStyle.accent,
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
            if (selectedScoreLabel != null && selectedScoreLabel!.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                selectedScoreLabel!,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.center,
              ),
            ],
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              alignment: WrapAlignment.end,
              children: [
                if (signalLabel != null && signalLabel!.isNotEmpty)
                  _MetricChip(
                    label: signalLabel!,
                    icon: Icons.sensors,
                    background: bandStyle.chipBackground,
                    foreground: bandStyle.chipForeground,
                  ),
                if (qualityBand != null && qualityBand!.isNotEmpty)
                  _MetricChip(
                    label: qualityBand!,
                    icon: Icons.verified_outlined,
                    background: bandStyle.chipBackground,
                    foreground: bandStyle.chipForeground,
                  ),
                if (weightLabel.isNotEmpty)
                  _MetricChip(
                    label: weightLabel,
                    icon: Icons.tune,
                    background: theme.colorScheme.surfaceContainerHighest,
                    foreground: theme.colorScheme.onSurface,
                  ),
              ],
            ),
            if (summary != null && summary!.isNotEmpty) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: theme.colorScheme.surface.withValues(alpha: 0.65),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  summary!,
                  style: theme.textTheme.bodyMedium?.copyWith(height: 1.45),
                  textAlign: TextAlign.left,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _MetricChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final Color background;
  final Color foreground;

  const _MetricChip({
    required this.label,
    required this.icon,
    required this.background,
    required this.foreground,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: foreground.withValues(alpha: 0.2)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: foreground),
          const SizedBox(width: 6),
          Text(
            label,
            style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: foreground,
                  fontWeight: FontWeight.w600,
                ),
          ),
        ],
      ),
    );
  }
}

class _ExplanationDetailsCard extends StatelessWidget {
  final List<String> details;

  const _ExplanationDetailsCard({required this.details});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.article_outlined, color: theme.colorScheme.primary, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'הסבר השוק',
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                    textAlign: TextAlign.right,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            ...details.map(
              (line) => Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Icon(
                        Icons.circle,
                        size: 6,
                        color: theme.colorScheme.primary,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        line,
                        style: theme.textTheme.bodyMedium,
                        textAlign: TextAlign.left,
                      ),
                    ),
                  ],
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
  final List<ScoreProbability> scores;
  final Color accent;

  const _TopScoresCard({required this.scores, required this.accent});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final maxProb = scores.map((s) => s.probability).fold<double>(
          0,
          (a, b) => a > b ? a : b,
        );

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.bar_chart_rounded, color: accent, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'תוצאות מובילות מותאמות לשוק',
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                    textAlign: TextAlign.right,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            ...scores.asMap().entries.map((entry) {
              final rank = entry.key + 1;
              final item = entry.value;
              final fraction = maxProb > 0 ? item.probability / maxProb : 0.0;
              final isTop = rank == 1;
              return Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                  decoration: isTop
                      ? BoxDecoration(
                          color: accent.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: accent.withValues(alpha: 0.35)),
                        )
                      : null,
                  child: Row(
                    children: [
                      SizedBox(
                        width: 52,
                        child: Text(
                          formatProbPercent(item.probability),
                          style: theme.textTheme.bodyMedium?.copyWith(
                            fontWeight: isTop ? FontWeight.w700 : FontWeight.w500,
                            color: isTop ? accent : null,
                          ),
                          textAlign: TextAlign.left,
                        ),
                      ),
                      Expanded(
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(4),
                          child: LinearProgressIndicator(
                            value: fraction.clamp(0.0, 1.0),
                            minHeight: 8,
                            backgroundColor: theme.colorScheme.surfaceContainerHighest,
                            color: isTop ? accent : accent.withValues(alpha: 0.55),
                          ),
                        ),
                      ),
                      const SizedBox(width: 10),
                      Directionality(
                        textDirection: TextDirection.ltr,
                        child: Text(
                          item.score,
                          style: theme.textTheme.titleSmall?.copyWith(
                            fontWeight: isTop ? FontWeight.w700 : FontWeight.w600,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Container(
                        width: 24,
                        height: 24,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: isTop
                              ? accent.withValues(alpha: 0.2)
                              : theme.colorScheme.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          '$rank',
                          style: theme.textTheme.labelSmall?.copyWith(
                            fontWeight: FontWeight.w700,
                            color: isTop ? accent : theme.colorScheme.onSurfaceVariant,
                          ),
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

class _TechnicalMarketDetails extends StatelessWidget {
  final MarketInfluenceApplied influence;
  final String? primaryScoreReason;

  const _TechnicalMarketDetails({
    required this.influence,
    this.primaryScoreReason,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = <({String label, String value})>[
      if (influence.providerEventId != null && influence.providerEventId!.isNotEmpty)
        (label: 'Event ID', value: influence.providerEventId!),
      if (influence.cacheStatus != null && influence.cacheStatus!.isNotEmpty)
        (label: 'Cache status', value: influence.cacheStatus!),
      if (influence.providerCallCount != null)
        (label: 'Provider calls', value: '${influence.providerCallCount}'),
      if ((primaryScoreReason ?? influence.primaryScoreReason)?.isNotEmpty == true)
        (
          label: 'Decision reason',
          value: primaryScoreReason ?? influence.primaryScoreReason ?? '',
        ),
    ];

    if (rows.isEmpty) return const SizedBox.shrink();

    return Card(
      margin: EdgeInsets.zero,
      child: Theme(
        data: theme.copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 16),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          initiallyExpanded: false,
          leading: Icon(Icons.settings_outlined, color: theme.colorScheme.primary),
          title: Text(
            'פרטי שוק טכניים',
            style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600),
          ),
          subtitle: const Text(
            'מזהה אירוע, מטמון וסיבת החלטה',
            textAlign: TextAlign.right,
          ),
          children: rows
              .map(
                (row) => Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        flex: 2,
                        child: Text(
                          row.label,
                          style: theme.textTheme.labelMedium?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                          textAlign: TextAlign.right,
                        ),
                      ),
                      Expanded(
                        flex: 3,
                        child: Text(
                          row.value,
                          style: theme.textTheme.bodySmall,
                          textAlign: TextAlign.left,
                        ),
                      ),
                    ],
                  ),
                ),
              )
              .toList(),
        ),
      ),
    );
  }
}

class _FooterNote extends StatelessWidget {
  final ThemeData theme;

  const _FooterNote({required this.theme});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline, size: 16, color: theme.colorScheme.onSurfaceVariant),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'התוצאה התקבלה מהשפעת שוק חי; מזהה האירוע נפתר אוטומטית בשרת.',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.right,
            ),
          ),
        ],
      ),
    );
  }
}
