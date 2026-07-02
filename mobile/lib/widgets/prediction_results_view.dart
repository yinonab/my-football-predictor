import 'package:flutter/material.dart';

import '../models/prediction_result.dart';
import '../models/venue_mode.dart';
import '../models/xg_model_variant.dart';
import '../utils/score_format.dart';
import '../utils/underdog_scoring_narrative.dart';
import 'matchup_goal_capability_card.dart';
import 'outcome_cards.dart';
import 'prediction_insight_sections.dart';
import 'prediction_market_panel.dart';
import 'score_list.dart';

enum PredictionResultTab { prediction, market, environment }

class PredictionResultsView extends StatefulWidget {
  final PredictionResult result;
  final VenueMode venueMode;
  final bool isNeutralGround;

  const PredictionResultsView({
    super.key,
    required this.result,
    required this.venueMode,
    this.isNeutralGround = true,
  });

  @override
  State<PredictionResultsView> createState() => _PredictionResultsViewState();
}

class _PredictionResultsViewState extends State<PredictionResultsView> {
  PredictionResultTab _tab = PredictionResultTab.prediction;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final result = widget.result;
    final matchupCapability = result.matchupGoalCapability;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'תוצאות חיזוי',
          style: theme.textTheme.titleLarge?.copyWith(
            fontWeight: FontWeight.bold,
          ),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 8),
        Text(
          '${shortTeamName(result.homeTeam)} נגד ${shortTeamName(result.awayTeam)}',
          style: theme.textTheme.titleMedium?.copyWith(
            color: theme.colorScheme.primary,
            fontWeight: FontWeight.w600,
          ),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 16),
        SegmentedButton<PredictionResultTab>(
          segments: const [
            ButtonSegment(
              value: PredictionResultTab.prediction,
              label: Text('תחזית'),
              icon: Icon(Icons.sports_soccer, size: 18),
            ),
            ButtonSegment(
              value: PredictionResultTab.market,
              label: Text('שוק'),
              icon: Icon(Icons.trending_up, size: 18),
            ),
            ButtonSegment(
              value: PredictionResultTab.environment,
              label: Text('סביבה'),
              icon: Icon(Icons.eco_outlined, size: 18),
            ),
          ],
          selected: {_tab},
          onSelectionChanged: (s) => setState(() => _tab = s.first),
        ),
        const SizedBox(height: 16),
        PredictionStatusBanner(result: result),
        if (result.modelDiagnostics?.modelVariantFallback == true) ...[
          const SizedBox(height: 8),
          Card(
            color: theme.colorScheme.errorContainer.withValues(alpha: 0.35),
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                'המודל הניסיוני נכשל, הוצגה תחזית NR3+FCC',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: theme.colorScheme.onErrorContainer,
                  fontWeight: FontWeight.w600,
                ),
                textAlign: TextAlign.right,
              ),
            ),
          ),
        ],
        if (result.modelDiagnostics != null) ...[
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.center,
            child: Chip(
              avatar: Icon(
                result.modelDiagnostics!.resolvedVariant ==
                        XgModelVariant.matchupRelativeV1
                    ? Icons.science_outlined
                    : Icons.verified_outlined,
                size: 18,
              ),
              label: Text(result.modelDiagnostics!.activeModelBadgeLabelResolved),
            ),
          ),
        ],
        PredictionDataLimitBanner(result: result),
        if (_tab == PredictionResultTab.prediction) ...[
          const SizedBox(height: 8),
          PredictionPrimaryScoreCard(
            result: result,
            isNeutralGround: widget.isNeutralGround,
          ),
          const SizedBox(height: 16),
          KeyProbabilitiesCard(
            probabilities: result.probabilities,
            teamALabel: result.homeTeam,
            teamBLabel: result.awayTeam,
            isNeutralGround: widget.isNeutralGround,
          ),
          const SizedBox(height: 16),
          ExpectedGoalsCard(result: result),
          if (matchupCapability != null) ...[
            const SizedBox(height: 16),
            MatchupGoalCapabilityCard(capability: matchupCapability),
          ],
          const SizedBox(height: 16),
          UnderdogScoringNarrativeCard(
            result: result,
            isNeutralGround: widget.isNeutralGround,
            compactWhenMatchupShown: matchupCapability != null,
          ),
          if (result.scorelineDecision != null) ...[
            const SizedBox(height: 12),
            PredictionWhyCard(
              result: result,
              requestedVenueMode: widget.venueMode,
            ),
          ] else if (result.matchSummary.isNotEmpty) ...[
            const SizedBox(height: 12),
            PredictionWhyCard(
              result: result,
              requestedVenueMode: widget.venueMode,
            ),
          ],
          if (result.h2hSummary.isNotEmpty) ...[
            const SizedBox(height: 12),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.history,
                      size: 22,
                      color: theme.colorScheme.secondary,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        result.h2hSummary,
                        style: theme.textTheme.bodyLarge,
                        textAlign: TextAlign.right,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 16),
          Text(
            'התוצאות האפשריות לפי הסתברות גולמית',
            style: theme.textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w600,
            ),
            textAlign: TextAlign.right,
          ),
          if (shouldShowTopScoresRepresentativeNote(result)) ...[
            const SizedBox(height: 8),
            Text(
              kTopScoresRepresentativeNote,
              style: theme.textTheme.bodyMedium?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.right,
            ),
          ],
          const SizedBox(height: 12),
          ScoreList(
            scores: result.topScores,
            teamAName: result.homeTeam,
            teamBName: result.awayTeam,
            isNeutralGround: widget.isNeutralGround,
            initialVisibleCount: 3,
          ),
          const SizedBox(height: 16),
          PredictionContextCard(
            result: result,
            requestedVenueMode: widget.venueMode,
          ),
          const SizedBox(height: 12),
          PredictionTechnicalDetails(
            result: result,
            requestedVenueMode: widget.venueMode,
            isNeutralGround: widget.isNeutralGround,
          ),
        ] else if (_tab == PredictionResultTab.market) ...[
          OutcomeCards(
            probabilities: result.probabilities,
            explanations: result.outcomeExplanations,
            teamALabel: result.homeTeam,
            teamBLabel: result.awayTeam,
            isNeutralGround: widget.isNeutralGround,
          ),
          const SizedBox(height: 12),
          PredictionMarketPanel(result: result),
        ] else ...[
          PredictionEnvironmentDataCard(result: result),
          const SizedBox(height: 8),
          PredictionContextCard(
            result: result,
            requestedVenueMode: widget.venueMode,
          ),
        ],
      ],
    );
  }
}

class KeyProbabilitiesCard extends StatelessWidget {
  final Probabilities1X2 probabilities;
  final String teamALabel;
  final String teamBLabel;
  final bool isNeutralGround;

  const KeyProbabilitiesCard({
    super.key,
    required this.probabilities,
    required this.teamALabel,
    required this.teamBLabel,
    this.isNeutralGround = true,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'הסתברויות עיקריות (1X2)',
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 12),
            OutcomeCards(
              probabilities: probabilities,
              explanations: const OutcomeExplanations(
                homeWin: '',
                draw: '',
                awayWin: '',
              ),
              teamALabel: teamALabel,
              teamBLabel: teamBLabel,
              isNeutralGround: isNeutralGround,
            ),
          ],
        ),
      ),
    );
  }
}
