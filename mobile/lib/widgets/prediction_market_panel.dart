import 'package:flutter/material.dart';

import '../models/market_diagnostics.dart';
import '../models/market_tab_view_model.dart';
import '../models/prediction_result.dart';
import '../utils/market_ui_copy.dart';

class PredictionMarketPanel extends StatelessWidget {
  final PredictionResult result;

  const PredictionMarketPanel({super.key, required this.result});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final vm = MarketTabViewModel.fromPredictionResult(result);
    final home = homeTeamShort(result);
    final away = awayTeamShort(result);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Icon(Icons.trending_up, color: theme.colorScheme.primary),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'שוק ההימורים',
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w600,
                    ),
                    textAlign: TextAlign.right,
                  ),
                ),
                _StatusChip(
                  label: marketStatusLabelHe(vm.statusMessage),
                  active: vm.marketDataAvailable,
                ),
              ],
            ),
            if (vm.primarySource != null) ...[
              const SizedBox(height: 6),
              Text(
                'מקור: ${vm.primarySource}',
                style: theme.textTheme.bodySmall,
                textAlign: TextAlign.right,
              ),
            ],
            const SizedBox(height: 16),
            Text(
              'השוואת הסתברויות 1X2',
              style: theme.textTheme.titleSmall,
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 8),
            _ComparisonTable(
              homeLabel: home,
              awayLabel: away,
              model: vm.modelProbabilities1x2,
              market: vm.marketConsensus1x2,
            ),
            const SizedBox(height: 16),
            Text(
              'ספרים / מקורות',
              style: theme.textTheme.titleSmall,
              textAlign: TextAlign.right,
            ),
            const SizedBox(height: 8),
            if (vm.bookmakers.isEmpty)
              _EmptyMarketState(status: vm.statusMessage)
            else
              ...vm.bookmakers.map(
                (q) => _BookmakerTile(
                  quote: q,
                  homeLabel: home,
                  awayLabel: away,
                ),
              ),
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest
                    .withValues(alpha: 0.6),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'הערות',
                    style: theme.textTheme.labelLarge,
                    textAlign: TextAlign.right,
                  ),
                  const SizedBox(height: 6),
                  ...buildMarketFootnotes(vm).map(
                    (line) => Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text(
                        '• $line',
                        style: theme.textTheme.bodySmall,
                        textAlign: TextAlign.right,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _StatusChip extends StatelessWidget {
  final String label;
  final bool active;

  const _StatusChip({required this.label, required this.active});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: active
            ? theme.colorScheme.primaryContainer
            : theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Text(
        label,
        style: theme.textTheme.labelSmall,
      ),
    );
  }
}

class _ComparisonTable extends StatelessWidget {
  final String homeLabel;
  final String awayLabel;
  final Map<String, double> model;
  final Map<String, double>? market;

  const _ComparisonTable({
    required this.homeLabel,
    required this.awayLabel,
    required this.model,
    this.market,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = <({String key, String label})>[
      (key: 'home_win', label: 'ניצחון $homeLabel'),
      (key: 'draw', label: 'תיקו'),
      (key: 'away_win', label: 'ניצחון $awayLabel'),
    ];

    return Table(
      columnWidths: const {
        0: FlexColumnWidth(2),
        1: FlexColumnWidth(1.2),
        2: FlexColumnWidth(1.2),
        3: FlexColumnWidth(1),
      },
      children: [
        TableRow(
          children: [
            _HeaderCell('תוצאה'),
            _HeaderCell('מודל'),
            _HeaderCell('שוק'),
            _HeaderCell('Δ'),
          ],
        ),
        ...rows.map((row) {
          final m = model[row.key];
          final mk = market?[row.key];
          return TableRow(
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 6),
                child: Text(
                  row.label,
                  style: theme.textTheme.bodyMedium,
                  textAlign: TextAlign.right,
                ),
              ),
              _ValueCell(formatProbPercent(m)),
              _ValueCell(formatProbPercent(mk)),
              _ValueCell(
                formatDelta(m, mk),
                emphasize: mk != null && m != null && (m - mk).abs() >= 5,
              ),
            ],
          );
        }),
      ],
    );
  }
}

class _HeaderCell extends StatelessWidget {
  final String text;
  const _HeaderCell(this.text);

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(
        text,
        style: Theme.of(context).textTheme.labelMedium,
        textAlign: TextAlign.center,
      ),
    );
  }
}

class _ValueCell extends StatelessWidget {
  final String text;
  final bool emphasize;

  const _ValueCell(this.text, {this.emphasize = false});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Text(
        text,
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              fontWeight: emphasize ? FontWeight.w600 : FontWeight.normal,
              color: emphasize ? Theme.of(context).colorScheme.primary : null,
            ),
        textAlign: TextAlign.center,
      ),
    );
  }
}

class _BookmakerTile extends StatelessWidget {
  final BookmakerQuote quote;
  final String homeLabel;
  final String awayLabel;

  const _BookmakerTile({
    required this.quote,
    required this.homeLabel,
    required this.awayLabel,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final implied = quote.implied1x2Percent;

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        border: Border.all(color: theme.colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              if (quote.isConsensus)
                Icon(Icons.hub_outlined, size: 16, color: theme.colorScheme.primary),
              if (quote.isConsensus) const SizedBox(width: 4),
              Expanded(
                child: Text(
                  quote.displayName,
                  style: theme.textTheme.titleSmall,
                  textAlign: TextAlign.right,
                ),
              ),
              if (quote.region.isNotEmpty)
                Text(
                  quote.region.toUpperCase(),
                  style: theme.textTheme.labelSmall,
                ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            '$homeLabel ${formatDecimalOdds(quote.homeDecimalOdds)} · '
            'תיקו ${formatDecimalOdds(quote.drawDecimalOdds)} · '
            '$awayLabel ${formatDecimalOdds(quote.awayDecimalOdds)}',
            style: theme.textTheme.bodySmall,
            textAlign: TextAlign.right,
          ),
          if (implied.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              'הסתברות משתמעת: '
              '${formatProbPercent(implied['home_win'])} / '
              '${formatProbPercent(implied['draw'])} / '
              '${formatProbPercent(implied['away_win'])}',
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
              textAlign: TextAlign.right,
            ),
          ],
        ],
      ),
    );
  }
}

class _EmptyMarketState extends StatelessWidget {
  final String status;

  const _EmptyMarketState({required this.status});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
  return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Icon(
            Icons.currency_exchange,
            size: 36,
            color: theme.colorScheme.onSurfaceVariant,
          ),
          const SizedBox(height: 8),
          Text(
            marketStatusLabelHe(status),
            style: theme.textTheme.bodyMedium,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 4),
          Text(
            'בשלב הבא יוצגו כאן מספר ספרים (Bet365, Pinnacle וכו\') '
            'לאחר חיבור השרת.',
            style: theme.textTheme.bodySmall,
            textAlign: TextAlign.center,
          ),
        ],
      ),
    );
  }
}
