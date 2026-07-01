import 'package:flutter/material.dart';

import '../models/prediction_result.dart';
import '../models/venue_mode.dart';
import '../utils/environment_ui_copy.dart';
import '../utils/prediction_ui_copy.dart';
import '../utils/score_format.dart';
import '../utils/underdog_scoring_narrative.dart';

class PredictionStatusBanner extends StatelessWidget {
  final PredictionResult result;

  const PredictionStatusBanner({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    if (!isMatchCompletedOrInvalid(result)) return const SizedBox.shrink();

    final theme = Theme.of(context);
    final actual = result.matchContextDiagnostics?.actualScore;
    final home = shortTeamName(result.homeTeam);
    final away = shortTeamName(result.awayTeam);

    return Card(
      color: theme.colorScheme.errorContainer.withValues(alpha: 0.55),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'המשחק כבר הסתיים',
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.right,
            ),
            if (actual != null) ...[
              const SizedBox(height: 6),
              Text(
                'תוצאה סופית: $home ${actual.home}–${actual.away} $away',
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.right,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class PredictionDataLimitBanner extends StatelessWidget {
  final PredictionResult result;

  const PredictionDataLimitBanner({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final message = buildConsolidatedDataLimitMessage(result);
    if (message == null) return const SizedBox.shrink();

    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.secondaryContainer.withValues(alpha: 0.45),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              Icons.info_outline,
              size: 18,
              color: theme.colorScheme.onSecondaryContainer,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                message,
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.right,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class PredictionPrimaryScoreCard extends StatelessWidget {
  final PredictionResult result;
  final bool isNeutralGround;

  const PredictionPrimaryScoreCard({
    super.key,
    required this.result,
    required this.isNeutralGround,
  });

  @override
  Widget build(BuildContext context) {
    if (isMatchCompletedOrInvalid(result)) {
      return const SizedBox.shrink();
    }

    final sd = result.scorelineDecision;
    final primary = sd?.primaryPredictedScore;
    if (primary == null) return const SizedBox.shrink();

    final theme = Theme.of(context);
    final scoreText = formatScorelineCandidate(
      primary,
      homeTeam: result.homeTeam,
      awayTeam: result.awayTeam,
      isNeutralGround: isNeutralGround,
    );

    final favoriteText = favoriteOutcomeText(
      outcome: sd!.favoriteOutcome,
      homeTeam: result.homeTeam,
      awayTeam: result.awayTeam,
    );

    return Card(
      color: theme.colorScheme.primaryContainer.withValues(alpha: 0.45),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'תחזית מרכזית',
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 8),
            Text(
              scoreText,
              style: theme.textTheme.headlineSmall?.copyWith(
                fontWeight: FontWeight.bold,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            Text(
              'תרחיש מוביל: $favoriteText (${sd.favoriteOutcomeProbability.toStringAsFixed(1)}%)',
              style: theme.textTheme.bodyMedium,
              textAlign: TextAlign.right,
            ),
          ],
        ),
      ),
    );
  }
}

class UnderdogScoringNarrativeCard extends StatelessWidget {
  final PredictionResult result;
  final bool isNeutralGround;

  const UnderdogScoringNarrativeCard({
    super.key,
    required this.result,
    this.isNeutralGround = true,
  });

  @override
  Widget build(BuildContext context) {
    if (isMatchCompletedOrInvalid(result)) {
      return const SizedBox.shrink();
    }

    final narrative = buildUnderdogScoringNarrative(
      result,
      isNeutralGround: isNeutralGround,
    );
    if (narrative == null) return const SizedBox.shrink();

    final theme = Theme.of(context);

    return Card(
      color: theme.colorScheme.secondaryContainer.withValues(alpha: 0.4),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'התחזית המרכזית היא שער נקי לפייבוריט, אבל המודל עדיין נותן לאנדרדוג סיכוי משמעותי להבקיע.',
              style: theme.textTheme.bodyMedium,
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 6),
            Text(
              'לכן מוצג גם תרחיש ריאלי שבו האנדרדוג כובש.',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 12),
            _NarrativeRow(
              label: 'סיכוי שהאנדרדוג יבקיע',
              value:
                  '${narrative.underdogTeamName}: ${narrative.underdogScoringProbabilityPercent.round()}%',
            ),
            for (final line in narrative.alternativeLines) ...[
              const SizedBox(height: 8),
              _NarrativeRow(
                label: line.label,
                value: line.isIllustration
                    ? line.scoreText
                    : line.probabilityPercent != null
                        ? '${line.scoreText} (${line.probabilityPercent!.toStringAsFixed(1)}%)'
                        : line.scoreText,
              ),
            ],
            if (narrative.bttsProbabilityPercent != null) ...[
              const SizedBox(height: 8),
              _NarrativeRow(
                label: 'שתי הקבוצות כובשות',
                value: '${narrative.bttsProbabilityPercent!.round()}%',
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _NarrativeRow extends StatelessWidget {
  final String label;
  final String value;

  const _NarrativeRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          label,
          style: theme.textTheme.labelMedium?.copyWith(
            fontWeight: FontWeight.w600,
          ),
          textAlign: TextAlign.right,
        ),
        const SizedBox(height: 4),
        Text(
          value,
          style: theme.textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w600,
          ),
          textAlign: TextAlign.center,
        ),
      ],
    );
  }
}

class PredictionWhyCard extends StatelessWidget {
  final PredictionResult result;
  final VenueMode? requestedVenueMode;

  const PredictionWhyCard({
    super.key,
    required this.result,
    this.requestedVenueMode,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final bullets = buildWhyPredictionBullets(
      result,
      requestedVenueMode: requestedVenueMode,
    );
    if (bullets.isEmpty) return const SizedBox.shrink();

    return Card(
      color: theme.colorScheme.surfaceContainerHighest,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'למה זו התחזית?',
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 8),
            ...bullets.map(
              (b) => Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text(
                  '• $b',
                  style: theme.textTheme.bodyMedium,
                  textAlign: TextAlign.right,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class PredictionContextCard extends StatelessWidget {
  final PredictionResult result;
  final VenueMode? requestedVenueMode;

  const PredictionContextCard({
    super.key,
    required this.result,
    this.requestedVenueMode,
  });

  @override
  Widget build(BuildContext context) {
    if (!shouldShowMatchContextCard(
      result,
      requestedVenueMode: requestedVenueMode,
    )) {
      return const SizedBox.shrink();
    }

    final theme = Theme.of(context);
    final diag = result.matchContextDiagnostics;
    final ctx = result.matchContext;
    final venueLine = venueContextSummaryLine(
      diag: diag,
      homeTeam: result.homeTeam,
      awayTeam: result.awayTeam,
      requestedVenueMode: requestedVenueMode,
    );
    final powerLine = homeAdvantagePowerDeltaLine(diag);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'הקשר משחק',
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 8),
            if (venueLine != null)
              Text(
                venueLine,
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.right,
              ),
            if (powerLine != null) ...[
              const SizedBox(height: 4),
              Text(
                powerLine,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.right,
              ),
            ],
            if (shouldShowRestDays(diag, ctx)) ...[
              const SizedBox(height: 6),
              Text(
                'ימי מנוחה: ${shortTeamName(result.homeTeam)} ${ctx!.homeRestDays} · ${shortTeamName(result.awayTeam)} ${ctx.awayRestDays}',
                style: theme.textTheme.bodySmall,
                textAlign: TextAlign.right,
              ),
            ],
            if (ctx?.weatherSummary != null &&
                ctx!.weatherSummary!.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(
                ctx.weatherSummary!,
                style: theme.textTheme.bodySmall,
                textAlign: TextAlign.right,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class PredictionEnvironmentDataCard extends StatelessWidget {
  final PredictionResult result;

  const PredictionEnvironmentDataCard({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    if (!shouldShowEnvironmentDataCard(result)) {
      return const SizedBox.shrink();
    }

    final theme = Theme.of(context);
    final lines = buildEnvironmentSummaryLines(result);
    final env = result.environmentDiagnostics;
    final isDiagnosticOnly = env?.automaticAltitudeAdjustmentMode ==
            'diagnostic_only' &&
        env?.weatherAdjustmentMode != 'active_existing';

    return Card(
      color: theme.colorScheme.tertiaryContainer.withValues(alpha: 0.35),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(
                  Icons.eco_outlined,
                  size: 20,
                  color: theme.colorScheme.onTertiaryContainer,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'סביבה ומקורות נתונים',
                    style: theme.textTheme.titleSmall?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                    textAlign: TextAlign.right,
                  ),
                ),
              ],
            ),
            if (isDiagnosticOnly) ...[
              const SizedBox(height: 6),
              Text(
                'הנתונים מוצגים לשקיפות — רובם עדיין לא משנים את החיזוי',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.right,
              ),
            ],
            const SizedBox(height: 8),
            ...lines.map(
              (line) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  '• $line',
                  style: theme.textTheme.bodyMedium,
                  textAlign: TextAlign.right,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class PredictionTechnicalDetails extends StatelessWidget {
  final PredictionResult result;
  final VenueMode? requestedVenueMode;
  final bool isNeutralGround;

  const PredictionTechnicalDetails({
    super.key,
    required this.result,
    this.requestedVenueMode,
    this.isNeutralGround = true,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final diag = result.matchContextDiagnostics;
    final ctx = result.matchContext;
    final hasContent = result.matchSummary.isNotEmpty ||
        result.outcomeExplanations.homeWin.isNotEmpty ||
        result.scoreCoverage.scores.isNotEmpty ||
        result.homeBreakdown.breakdown.isNotEmpty;

    if (!hasContent) return const SizedBox.shrink();

    return Card(
      margin: EdgeInsets.zero,
      child: Theme(
        data: theme.copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 16),
          childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          initiallyExpanded: false,
          leading: Icon(Icons.tune, color: theme.colorScheme.primary),
          title: Text(
            'פרטים טכניים',
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w600,
            ),
          ),
          subtitle: const Text(
            'דירוגים, הסברי מודל ונתוני מקור',
            textAlign: TextAlign.right,
          ),
          children: [
            _TeamStrengthSection(result: result),
            if (result.matchSummary.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                result.matchSummary,
                style: theme.textTheme.bodySmall,
                textAlign: TextAlign.right,
              ),
            ],
            if (result.outcomeExplanations.homeWin.isNotEmpty ||
                result.outcomeExplanations.draw.isNotEmpty ||
                result.outcomeExplanations.awayWin.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'הסברי תוצאות (מודל)',
                style: theme.textTheme.labelLarge,
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 4),
              if (result.outcomeExplanations.homeWin.isNotEmpty)
                _TechnicalLine(
                  title: shortTeamName(result.homeTeam),
                  text: result.outcomeExplanations.homeWin,
                ),
              if (result.outcomeExplanations.draw.isNotEmpty)
                _TechnicalLine(title: 'תיקו', text: result.outcomeExplanations.draw),
              if (result.outcomeExplanations.awayWin.isNotEmpty)
                _TechnicalLine(
                  title: shortTeamName(result.awayTeam),
                  text: result.outcomeExplanations.awayWin,
                ),
            ],
            if (result.scoreCoverage.scores.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'טווח תוצאות (${result.scoreCoverage.achievedPercent.toStringAsFixed(0)}% מהמסה)',
                style: theme.textTheme.labelLarge,
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                alignment: WrapAlignment.end,
                children: result.scoreCoverage.scores
                    .map(
                      (s) => Chip(
                        label: Text(
                          formatNamedScore(
                            s,
                            teamAName: result.homeTeam,
                            teamBName: result.awayTeam,
                            isNeutralGround: isNeutralGround,
                          ),
                        ),
                      ),
                    )
                    .toList(),
              ),
              if (result.scoreCoverage.explanation.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  result.scoreCoverage.explanation,
                  style: theme.textTheme.bodySmall,
                  textAlign: TextAlign.right,
                ),
              ],
            ],
            if (result.environmentDiagnostics != null ||
                result.recentFormProviderDiagnostics != null) ...[
              const SizedBox(height: 12),
              Text(
                'סביבה ומקורות',
                style: theme.textTheme.labelLarge,
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 4),
              ...buildEnvironmentSummaryLines(result).map(
                (line) => Text(
                  line,
                  style: theme.textTheme.bodySmall,
                  textAlign: TextAlign.right,
                ),
              ),
            ],
            if (diag != null || ctx != null) ...[
              const SizedBox(height: 12),
              Text(
                'אבחון הקשר',
                style: theme.textTheme.labelLarge,
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 4),
              if (diag != null) ...[
                Text(
                  'מקור משחק: ${diag.fixtureSourceAvailable ? "זמין" : "לא זמין"} · '
                  'אצטדיון: ${diag.venueContextAvailable ? "זמין" : "לא זמין"}',
                  style: theme.textTheme.bodySmall,
                  textAlign: TextAlign.right,
                ),
                if (ctx?.matchDate != null)
                  Text(
                    'תאריך במערכת: ${ctx!.matchDate}',
                    style: theme.textTheme.bodySmall,
                    textAlign: TextAlign.right,
                  ),
                if (diag.warnings.isNotEmpty)
                  Text(
                    'אזהרות: ${diag.warnings.join(", ")}',
                    style: theme.textTheme.bodySmall,
                    textAlign: TextAlign.right,
                  ),
              ],
            ],
            if (result.scorelineDecision?.warnings.isNotEmpty == true) ...[
              const SizedBox(height: 8),
              Text(
                'אזהרות תחזית: ${result.scorelineDecision!.warnings.join(", ")}',
                style: theme.textTheme.bodySmall,
                textAlign: TextAlign.right,
              ),
            ],
            if (result.scorelineDecision?.representativeSelection.isNotEmpty ==
                true) ...[
              const SizedBox(height: 8),
              Text(
                'בחירת תוצאה מייצגת: '
                '${result.scorelineDecision!.representativeSelection}',
                style: theme.textTheme.bodySmall,
                textAlign: TextAlign.right,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _TeamStrengthSection extends StatelessWidget {
  final PredictionResult result;

  const _TeamStrengthSection({required this.result});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'פירוט כוח נבחרות',
          style: theme.textTheme.labelLarge,
          textAlign: TextAlign.right,
        ),
        const SizedBox(height: 8),
        _TeamStrengthBlock(
          label: shortTeamName(result.homeTeam),
          breakdown: result.homeBreakdown,
          power: result.homePower,
        ),
        const SizedBox(height: 8),
        _TeamStrengthBlock(
          label: shortTeamName(result.awayTeam),
          breakdown: result.awayBreakdown,
          power: result.awayPower,
        ),
      ],
    );
  }
}

class _TeamStrengthBlock extends StatelessWidget {
  final String label;
  final TeamBreakdown breakdown;
  final double power;

  const _TeamStrengthBlock({
    required this.label,
    required this.breakdown,
    required this.power,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = parseBreakdownRows(breakdown.breakdown);

    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Text(
                'כוח כולל: ${power.toStringAsFixed(0)}',
                style: theme.textTheme.titleSmall,
              ),
              const Spacer(),
              Text(label, style: theme.textTheme.titleSmall),
            ],
          ),
          if (rows.isNotEmpty) ...[
            const SizedBox(height: 6),
            for (final row in rows)
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text(
                  '${row.key}: ${row.value}',
                  style: theme.textTheme.bodySmall,
                  textAlign: TextAlign.right,
                ),
              ),
          ] else if (breakdown.breakdown.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              breakdown.breakdown,
              style: theme.textTheme.bodySmall,
              textAlign: TextAlign.right,
            ),
          ],
        ],
      ),
    );
  }
}

class _TechnicalLine extends StatelessWidget {
  final String title;
  final String text;

  const _TechnicalLine({required this.title, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.labelMedium,
            textAlign: TextAlign.right,
          ),
          Text(
            text,
            style: Theme.of(context).textTheme.bodySmall,
            textAlign: TextAlign.right,
          ),
        ],
      ),
    );
  }
}

class ExpectedGoalsCard extends StatelessWidget {
  final PredictionResult result;

  const ExpectedGoalsCard({super.key, required this.result});

  String _formatPair(double home, double away) {
    return '${shortTeamName(result.homeTeam)}: ${home.toStringAsFixed(2)}  |  '
        '${shortTeamName(result.awayTeam)}: ${away.toStringAsFixed(2)}';
  }

  String _statusLabel(String status) {
    switch (status) {
      case 'applied':
        return 'הופעל';
      case 'disabled':
        return 'כבוי';
      case 'skipped':
        return 'דולג';
      default:
        return status;
    }
  }

  Widget _adjustmentRow(BuildContext context, Nr3XgAdjustment adj) {
    final theme = Theme.of(context);
    final deltaText =
        'Δ ${adj.deltaHomeXg >= 0 ? '+' : ''}${adj.deltaHomeXg.toStringAsFixed(2)}'
        ' / ${adj.deltaAwayXg >= 0 ? '+' : ''}${adj.deltaAwayXg.toStringAsFixed(2)}';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  adj.displayName,
                  style: theme.textTheme.labelLarge,
                  textAlign: TextAlign.right,
                ),
              ),
              Text(
                _statusLabel(adj.status),
                style: theme.textTheme.labelSmall?.copyWith(
                  color: theme.colorScheme.primary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            '${_formatPair(adj.beforeHomeXg, adj.beforeAwayXg)} → '
            '${_formatPair(adj.afterHomeXg, adj.afterAwayXg)}',
            style: theme.textTheme.bodySmall,
            textAlign: TextAlign.center,
          ),
          if (adj.status == 'applied' &&
              (adj.deltaHomeXg.abs() > 0.001 || adj.deltaAwayXg.abs() > 0.001))
            Text(
              deltaText,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.secondary,
              ),
              textAlign: TextAlign.center,
            ),
          if (adj.explanation.isNotEmpty)
            Text(
              adj.explanation,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.right,
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final decomp = result.nr3XgDecomposition;

    if (decomp != null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                decomp.finalXg.label.isNotEmpty
                    ? decomp.finalXg.label
                    : 'xG סופי לחיזוי',
                style: theme.textTheme.titleSmall?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 8),
              Text(
                _formatPair(result.homeXg, result.awayXg),
                style: theme.textTheme.titleMedium?.copyWith(
                  fontWeight: FontWeight.w600,
                ),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text(
                  'פירוט חישוב NR3',
                  style: theme.textTheme.labelLarge,
                  textAlign: TextAlign.right,
                ),
                children: [
                  Align(
                    alignment: Alignment.centerRight,
                    child: Text(
                      decomp.nr3Base.label,
                      style: theme.textTheme.labelMedium,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _formatPair(decomp.nr3Base.homeXg, decomp.nr3Base.awayXg),
                    style: theme.textTheme.bodyMedium,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  Align(
                    alignment: Alignment.centerRight,
                    child: Text(
                      'התאמות שהופעלו',
                      style: theme.textTheme.labelMedium,
                    ),
                  ),
                  const SizedBox(height: 8),
                  ...decomp.adjustments.map((a) => _adjustmentRow(context, a)),
                  const Divider(),
                  Align(
                    alignment: Alignment.centerRight,
                    child: Text(
                      'xG סופי של המודל',
                      style: theme.textTheme.labelMedium,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _formatPair(decomp.finalXg.homeXg, decomp.finalXg.awayXg),
                    style: theme.textTheme.bodyMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 12),
                  Align(
                    alignment: Alignment.centerRight,
                    child: Text(
                      decomp.legacyReference.label,
                      style: theme.textTheme.labelMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _formatPair(
                      decomp.legacyReference.homeXg,
                      decomp.legacyReference.awayXg,
                    ),
                    style: theme.textTheme.bodySmall,
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    decomp.legacyReference.note,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                      fontStyle: FontStyle.italic,
                    ),
                    textAlign: TextAlign.right,
                  ),
                ],
              ),
            ],
          ),
        ),
      );
    }

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'שערים צפויים',
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 8),
            Text(
              _formatPair(result.homeXg, result.awayXg),
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 6),
            Text(
              'זהו אומדן לכמות השערים הצפויה, לא תוצאה מובטחת.',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.right,
            ),
          ],
        ),
      ),
    );
  }
}
