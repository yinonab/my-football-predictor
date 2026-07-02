import 'package:flutter/material.dart';

import '../models/matchup_goal_capability.dart';
import '../utils/score_format.dart';

class MatchupGoalCapabilityCard extends StatelessWidget {
  final MatchupGoalCapability capability;

  const MatchupGoalCapabilityCard({super.key, required this.capability});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final favShort = shortTeamName(capability.favoriteTeam);
    final udShort = shortTeamName(capability.underdogTeam);

    return Card(
      color: theme.colorScheme.primaryContainer.withValues(alpha: 0.35),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              capability.summary.title,
              style: theme.textTheme.titleMedium?.copyWith(
                fontWeight: FontWeight.bold,
              ),
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 16),
            _CapabilityRow(
              label: 'יכולת $favShort להבקיע',
              level: capability.favoriteGoalCapability,
            ),
            const SizedBox(height: 12),
            _CapabilityRow(
              label: 'יכולת $udShort להבקיע',
              level: capability.underdogGoalCapability,
            ),
            const SizedBox(height: 12),
            _ProbabilityRow(
              label: 'סיכוי ש-$udShort תבקיע',
              percent: capability.probabilities.underdogScoresProbability,
            ),
            if (capability.cleanSheetRisk != null &&
                capability.cleanSheetRisk != GoalCapabilityLevel.low) ...[
              const SizedBox(height: 12),
              _CapabilityRow(
                label: 'סיכון לשער נקי',
                level: capability.cleanSheetRisk,
              ),
            ],
            const SizedBox(height: 12),
            _CapabilityRow(
              label: 'שתי הקבוצות כובשות',
              level: capability.bttsLikelihood,
            ),
            if (capability.summary.cleanSheetText.isNotEmpty) ...[
              const SizedBox(height: 16),
              Text(
                capability.summary.cleanSheetText,
                style: theme.textTheme.bodyLarge,
                textAlign: TextAlign.right,
              ),
            ],
            if (capability.summary.underdogText.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                capability.summary.underdogText,
                style: theme.textTheme.bodyLarge,
                textAlign: TextAlign.right,
              ),
            ],
            if (capability.summary.favoriteText.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text(
                capability.summary.favoriteText,
                style: theme.textTheme.bodyLarge,
                textAlign: TextAlign.right,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _CapabilityRow extends StatelessWidget {
  final String label;
  final GoalCapabilityLevel? level;

  const _CapabilityRow({required this.label, required this.level});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          label,
          style: theme.textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w600,
          ),
          textAlign: TextAlign.right,
        ),
        const SizedBox(height: 6),
        Align(
          alignment: Alignment.centerRight,
          child: _LevelBadge(level: level),
        ),
      ],
    );
  }
}

class _ProbabilityRow extends StatelessWidget {
  final String label;
  final double percent;

  const _ProbabilityRow({required this.label, required this.percent});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          label,
          style: theme.textTheme.titleSmall?.copyWith(
            fontWeight: FontWeight.w600,
          ),
          textAlign: TextAlign.right,
        ),
        const SizedBox(height: 6),
        Text(
          '${percent.round()}%',
          style: theme.textTheme.headlineSmall?.copyWith(
            fontWeight: FontWeight.bold,
          ),
          textAlign: TextAlign.center,
        ),
      ],
    );
  }
}

class _LevelBadge extends StatelessWidget {
  final GoalCapabilityLevel? level;

  const _LevelBadge({required this.level});

  Color _color(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    switch (level) {
      case GoalCapabilityLevel.high:
        return scheme.errorContainer;
      case GoalCapabilityLevel.medium:
        return scheme.tertiaryContainer;
      case GoalCapabilityLevel.low:
      case null:
        return scheme.surfaceContainerHighest;
    }
  }

  Color _textColor(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    switch (level) {
      case GoalCapabilityLevel.high:
        return scheme.onErrorContainer;
      case GoalCapabilityLevel.medium:
        return scheme.onTertiaryContainer;
      case GoalCapabilityLevel.low:
      case null:
        return scheme.onSurfaceVariant;
    }
  }

  @override
  Widget build(BuildContext context) {
    final label = level == null ? '—' : goalCapabilityLevelHebrew(level!);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      decoration: BoxDecoration(
        color: _color(context),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.bold,
              color: _textColor(context),
            ),
      ),
    );
  }
}
