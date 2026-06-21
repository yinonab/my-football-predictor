import 'package:flutter/material.dart';

import '../utils/score_format.dart';
import '../models/prediction_result.dart';

class ScoreList extends StatefulWidget {
  final List<ScoreProbability> scores;
  final String? teamAName;
  final String? teamBName;
  final bool isNeutralGround;
  final int initialVisibleCount;
  final bool showExplanations;

  const ScoreList({
    super.key,
    required this.scores,
    this.teamAName,
    this.teamBName,
    this.isNeutralGround = true,
    this.initialVisibleCount = 3,
    this.showExplanations = false,
  });

  @override
  State<ScoreList> createState() => _ScoreListState();
}

class _ScoreListState extends State<ScoreList> {
  bool _expanded = false;

  String _formatScore(String raw) {
    return formatNamedScore(
      raw,
      teamAName: widget.teamAName ?? 'נבחרת א\'',
      teamBName: widget.teamBName ?? 'נבחרת ב\'',
      isNeutralGround: widget.isNeutralGround,
    );
  }

  String? _shortExplanation(String explanation) {
    final trimmed = explanation.trim();
    if (trimmed.isEmpty) return null;
    if (trimmed.length <= 80) return trimmed;
    return '${trimmed.substring(0, 77).trimRight()}…';
  }

  @override
  Widget build(BuildContext context) {
    if (widget.scores.isEmpty) return const SizedBox.shrink();

    final theme = Theme.of(context);
    final visibleCount = _expanded
        ? widget.scores.length
        : widget.initialVisibleCount.clamp(0, widget.scores.length);
    final visible = widget.scores.take(visibleCount).toList();
    final hasMore = widget.scores.length > widget.initialVisibleCount;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Card(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
          child: Column(
            children: [
              for (var i = 0; i < visible.length; i++) ...[
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
                              '${visible[i].probability.toStringAsFixed(1)}%',
                              style: theme.textTheme.labelLarge?.copyWith(
                                color: theme.colorScheme.onPrimaryContainer,
                                fontWeight: FontWeight.bold,
                              ),
                            ),
                          ),
                          const Spacer(),
                          Text(
                            _formatScore(visible[i].score),
                            style: theme.textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ],
                      ),
                      if (widget.showExplanations) ...[
                        Builder(
                          builder: (context) {
                            final short =
                                _shortExplanation(visible[i].explanation);
                            if (short == null) return const SizedBox.shrink();
                            return Padding(
                              padding: const EdgeInsets.only(top: 6),
                              child: Text(
                                short,
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onSurfaceVariant,
                                ),
                                textAlign: TextAlign.right,
                              ),
                            );
                          },
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ],
          ),
        ),
        if (hasMore)
          TextButton.icon(
            onPressed: () => setState(() => _expanded = !_expanded),
            icon: Icon(_expanded ? Icons.expand_less : Icons.expand_more),
            label: Text(
              _expanded
                  ? 'הצג פחות תוצאות'
                  : 'הצג עוד תוצאות אפשריות (${widget.scores.length - widget.initialVisibleCount})',
            ),
          ),
      ],
    );
  }
}
