import 'package:flutter/material.dart';

import '../models/prediction_result.dart';

class ScoreList extends StatelessWidget {
  final List<ScoreProbability> scores;
  final String? teamAName;
  final String? teamBName;
  final bool isNeutralGround;

  const ScoreList({
    super.key,
    required this.scores,
    this.teamAName,
    this.teamBName,
    this.isNeutralGround = true,
  });

  String _formatScore(String raw) {
    final parts = raw.split('-');
    if (parts.length != 2) return raw;

    if (isNeutralGround) {
      return '${parts[0]} - ${parts[1]}';
    }

    final a = teamAName != null ? _shortName(teamAName!) : 'מארחת';
    final b = teamBName != null ? _shortName(teamBName!) : 'אורחת';
    return '${parts[0]} ($a) - ${parts[1]} ($b)';
  }

  String _shortName(String full) {
    final match = RegExp(r'\(([^)]+)\)').firstMatch(full);
    return match?.group(1) ?? full;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: Column(
        children: [
          for (var i = 0; i < scores.length; i++) ...[
            if (i > 0) const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 6,
                        ),
                        decoration: BoxDecoration(
                          color: theme.colorScheme.primaryContainer,
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Text(
                          '${scores[i].probability.toStringAsFixed(1)}%',
                          style: theme.textTheme.labelLarge?.copyWith(
                            color: theme.colorScheme.onPrimaryContainer,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ),
                      const Spacer(),
                      Text(
                        _formatScore(scores[i].score),
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                  if (scores[i].explanation.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      scores[i].explanation,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                      textAlign: TextAlign.right,
                    ),
                  ],
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}
