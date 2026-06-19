import 'package:flutter/material.dart';

import '../models/prediction_result.dart';
import '../models/venue_mode.dart';
import '../utils/prediction_ui_copy.dart';
import '../utils/score_format.dart';

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

class PredictionWarningChips extends StatelessWidget {
  final PredictionResult result;

  const PredictionWarningChips({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final lines = buildUserWarningLines(result);
    if (lines.isEmpty) return const SizedBox.shrink();

    final theme = Theme.of(context);
    return Wrap(
      spacing: 8,
      runSpacing: 8,
      alignment: WrapAlignment.end,
      children: lines
          .map(
            (line) => Chip(
              avatar: Icon(
                Icons.info_outline,
                size: 16,
                color: theme.colorScheme.onSecondaryContainer,
              ),
              label: Text(line),
              backgroundColor: theme.colorScheme.secondaryContainer,
            ),
          )
          .toList(),
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
              'תחזית תוצאה מרכזית',
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
              'התרחיש המוביל: $favoriteText — '
              '${sd.favoriteOutcomeProbability.toStringAsFixed(1)}%',
              style: theme.textTheme.bodyMedium,
              textAlign: TextAlign.right,
            ),
            if (sd.topExactScoreDiffersFromPrimary &&
                sd.topExactScoreOverall != null) ...[
              const SizedBox(height: 8),
              Text(
                'התוצאה הבודדת הנפוצה ביותר במודל: '
                '${formatScorelineCandidate(
                  sd.topExactScoreOverall!,
                  homeTeam: result.homeTeam,
                  awayTeam: result.awayTeam,
                  isNeutralGround: isNeutralGround,
                )}',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.right,
              ),
            ],
          ],
        ),
      ),
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
    final theme = Theme.of(context);
    final diag = result.matchContextDiagnostics;
    final ctx = result.matchContext;
    final reliable = isFixtureContextReliable(diag);
    final venueLine = venueContextSummaryLine(
      diag: diag,
      homeTeam: result.homeTeam,
      awayTeam: result.awayTeam,
      requestedVenueMode: requestedVenueMode,
    );
    final powerLine = homeAdvantagePowerDeltaLine(diag);

    return Card(
      color: theme.colorScheme.tertiaryContainer.withValues(alpha: 0.45),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(
                  Icons.wb_sunny_outlined,
                  size: 20,
                  color: theme.colorScheme.tertiary,
                ),
                const SizedBox(width: 8),
                Text(
                  'הקשר משחק',
                  style: theme.textTheme.titleSmall?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (venueLine != null) ...[
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
              const SizedBox(height: 8),
            ],
            if (!reliable) ...[
              Text(
                'נתוני מועד, אצטדיון והקשר משחק אינם זמינים כרגע.',
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 4),
              Text(
                'התחזית מבוססת בעיקר על חוזק הקבוצות, xG ותוצאות עבר.',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.right,
              ),
            ] else ...[
              Text(
                'ביתיות: ${diag?.hostAdvantageApplied == true ? 'הופעלה' : 'לא הופעלה'}',
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 4),
              Text(
                'אצטדיון: ${diag?.venueContextAvailable == true ? 'זמין' : 'לא זמין'}',
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 4),
              Text(
                'נתוני מנוחה: ${shouldShowRestDays(diag, ctx) ? 'זמינים' : 'לא זמינים'}',
                style: theme.textTheme.bodyMedium,
                textAlign: TextAlign.right,
              ),
              if (shouldShowRestDays(diag, ctx)) ...[
                const SizedBox(height: 6),
                Text(
                  'מנוחה: בית ${ctx!.homeRestDays} ימים · חוץ ${ctx.awayRestDays} ימים',
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
          ],
        ),
      ),
    );
  }
}

class PredictionTechnicalDetails extends StatelessWidget {
  final PredictionResult result;

  const PredictionTechnicalDetails({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    if (result.matchSummary.isEmpty) return const SizedBox.shrink();

    return ExpansionTile(
      title: const Text('פרטים טכניים'),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: Text(
            result.matchSummary,
            style: Theme.of(context).textTheme.bodySmall,
            textAlign: TextAlign.right,
          ),
        ),
      ],
    );
  }
}
