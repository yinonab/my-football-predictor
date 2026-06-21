import 'package:flutter/material.dart';

import '../models/prediction_result.dart';

class OutcomeCards extends StatelessWidget {
  final Probabilities1X2 probabilities;
  final OutcomeExplanations explanations;
  final String teamALabel;
  final String teamBLabel;
  final bool isNeutralGround;
  final bool showExplanations;

  const OutcomeCards({
    super.key,
    required this.probabilities,
    required this.explanations,
    required this.teamALabel,
    required this.teamBLabel,
    this.isNeutralGround = true,
    this.showExplanations = false,
  });

  @override
  Widget build(BuildContext context) {
    final teamA = _shortName(teamALabel);
    final teamB = _shortName(teamBLabel);
    final sideALabel = isNeutralGround ? 'נבחרת א\'' : 'מארחת';
    final sideBLabel = isNeutralGround ? 'נבחרת ב\'' : 'אורחת';

    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: _OutcomeCard(
                sideLabel: sideALabel,
                team: teamA,
                percent: probabilities.homeWin,
                color: Colors.green.shade600,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _OutcomeCard(
                sideLabel: 'תיקו',
                team: 'X',
                percent: probabilities.draw,
                color: Colors.orange.shade600,
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: _OutcomeCard(
                sideLabel: sideBLabel,
                team: teamB,
                percent: probabilities.awayWin,
                color: Colors.blue.shade600,
              ),
            ),
          ],
        ),
        if (showExplanations) ...[
          const SizedBox(height: 12),
          _ExplanationTile(
            title: '$sideALabel ($teamA)',
            text: explanations.homeWin,
          ),
          _ExplanationTile(title: 'תיקו', text: explanations.draw),
          _ExplanationTile(
            title: '$sideBLabel ($teamB)',
            text: explanations.awayWin,
          ),
        ],
      ],
    );
  }

  String _shortName(String full) {
    final match = RegExp(r'\(([^)]+)\)').firstMatch(full);
    return match?.group(1) ?? full;
  }
}

class _ExplanationTile extends StatelessWidget {
  final String title;
  final String text;

  const _ExplanationTile({required this.title, required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                title,
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
                textAlign: TextAlign.right,
              ),
              const SizedBox(height: 4),
              Text(
                text,
                style: Theme.of(context).textTheme.bodySmall,
                textAlign: TextAlign.right,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _OutcomeCard extends StatelessWidget {
  final String sideLabel;
  final String team;
  final double percent;
  final Color color;

  const _OutcomeCard({
    required this.sideLabel,
    required this.team,
    required this.percent,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 2,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 8),
        child: Column(
          children: [
            Text(
              '${percent.toStringAsFixed(1)}%',
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
            const SizedBox(height: 4),
            Text(sideLabel, style: Theme.of(context).textTheme.labelMedium),
            Text(
              team,
              style: Theme.of(context).textTheme.bodySmall,
              textAlign: TextAlign.center,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
          ],
        ),
      ),
    );
  }
}
