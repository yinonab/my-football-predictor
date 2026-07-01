import 'package:flutter/material.dart';

import '../models/prediction_result.dart';
import '../models/venue_mode.dart';
import '../utils/score_format.dart';
import '../utils/underdog_scoring_narrative.dart';
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
        const SizedBox(height: 12),
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
        OutcomeCards(
          probabilities: result.probabilities,
          explanations: result.outcomeExplanations,
          teamALabel: result.homeTeam,
          teamBLabel: result.awayTeam,
          isNeutralGround: widget.isNeutralGround,
        ),
        const SizedBox(height: 12),
        PredictionStatusBanner(result: result),
        PredictionDataLimitBanner(result: result),
        const SizedBox(height: 12),
        if (_tab == PredictionResultTab.prediction) ...[
          PredictionPrimaryScoreCard(
            result: result,
            isNeutralGround: widget.isNeutralGround,
          ),
          const SizedBox(height: 8),
          UnderdogScoringNarrativeCard(
            result: result,
            isNeutralGround: widget.isNeutralGround,
          ),
          if (result.scorelineDecision != null) ...[
            const SizedBox(height: 8),
            PredictionWhyCard(
              result: result,
              requestedVenueMode: widget.venueMode,
            ),
          ] else if (result.matchSummary.isNotEmpty) ...[
            const SizedBox(height: 8),
            PredictionWhyCard(
              result: result,
              requestedVenueMode: widget.venueMode,
            ),
          ],
          if (result.h2hSummary.isNotEmpty) ...[
            const SizedBox(height: 8),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.history,
                      size: 20,
                      color: theme.colorScheme.secondary,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        result.h2hSummary,
                        style: theme.textTheme.bodyMedium,
                        textAlign: TextAlign.right,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
          const SizedBox(height: 12),
          ExpectedGoalsCard(result: result),
          const SizedBox(height: 16),
          Text(
            'תוצאות אפשריות מובילות',
            style: theme.textTheme.titleMedium,
            textAlign: TextAlign.right,
          ),
          if (shouldShowTopScoresRepresentativeNote(result)) ...[
            const SizedBox(height: 4),
            Text(
              kTopScoresRepresentativeNote,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.right,
            ),
          ],
          const SizedBox(height: 8),
          ScoreList(
            scores: result.topScores,
            teamAName: result.homeTeam,
            teamBName: result.awayTeam,
            isNeutralGround: widget.isNeutralGround,
            initialVisibleCount: 3,
          ),
          const SizedBox(height: 12),
          PredictionContextCard(
            result: result,
            requestedVenueMode: widget.venueMode,
          ),
          const SizedBox(height: 8),
          PredictionTechnicalDetails(
            result: result,
            requestedVenueMode: widget.venueMode,
            isNeutralGround: widget.isNeutralGround,
          ),
        ] else if (_tab == PredictionResultTab.market) ...[
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
