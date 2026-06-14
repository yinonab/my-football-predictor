import 'package:flutter/material.dart';

import '../models/prediction_result.dart';
import '../services/api_service.dart';

class TournamentScreen extends StatefulWidget {
  final PredictionSettings settings;
  final ApiService apiService;

  const TournamentScreen({
    super.key,
    required this.settings,
    required this.apiService,
  });

  @override
  State<TournamentScreen> createState() => _TournamentScreenState();
}

class _TournamentScreenState extends State<TournamentScreen> {
  String _selectedGroup = 'A';
  List<GroupStanding>? _groupStandings;
  List<ChampionOdds>? _championOdds;
  bool _loadingGroup = false;
  bool _loadingChampion = false;
  String? _error;
  late PredictionSettings _settings;

  @override
  void initState() {
    super.initState();
    _settings = widget.settings;
    _refreshSettings();
  }

  Future<void> _refreshSettings() async {
    final s = await widget.apiService.loadSettings();
    if (mounted) setState(() => _settings = s);
  }

  Future<void> _simulateGroup() async {
    setState(() {
      _loadingGroup = true;
      _error = null;
    });
    try {
      final result = await widget.apiService.simulateGroup(
        baseUrl: _settings.apiBaseUrl,
        group: _selectedGroup,
      );
      if (!mounted) return;
      setState(() {
        _groupStandings = result;
        _loadingGroup = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loadingGroup = false;
      });
    }
  }

  Future<void> _simulateChampion() async {
    setState(() {
      _loadingChampion = true;
      _error = null;
    });
    try {
      final result = await widget.apiService.simulateChampion(
        baseUrl: _settings.apiBaseUrl,
        iterations: 800,
      );
      if (!mounted) return;
      setState(() {
        _championOdds = result;
        _loadingChampion = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loadingChampion = false;
      });
    }
  }

  String _shortName(String full) {
    final match = RegExp(r'\(([^)]+)\)').firstMatch(full);
    return match?.group(1) ?? full;
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Directionality(
      textDirection: TextDirection.rtl,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(
            'סימולציית Monte Carlo',
            style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 8),
          Text(
            '500–800 הרצות סטochastic לפי המודל הנוכחי',
            style: theme.textTheme.bodySmall,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 24),
          Text('סימולציית בית', style: theme.textTheme.titleMedium),
          const SizedBox(height: 8),
          InputDecorator(
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
              labelText: 'בחר בית',
            ),
            child: DropdownButtonHideUnderline(
              child: DropdownButton<String>(
                value: _selectedGroup,
                isExpanded: true,
                items: 'ABCDEFGHIJKL'
                    .split('')
                    .map((g) => DropdownMenuItem(value: g, child: Text('בית $g')))
                    .toList(),
                onChanged: (v) => setState(() => _selectedGroup = v ?? 'A'),
              ),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _loadingGroup ? null : _simulateGroup,
            icon: _loadingGroup
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.groups),
            label: Text(_loadingGroup ? 'מחשב...' : 'סמלץ בית $_selectedGroup'),
          ),
          if (_groupStandings != null) ...[
            const SizedBox(height: 16),
            Card(
              child: Column(
                children: [
                  for (final row in _groupStandings!) ...[
                    ListTile(
                      title: Text(_shortName(row.team)),
                      subtitle: Text(
                        'ממוצע נק\' ${row.avgPoints.toStringAsFixed(1)}',
                      ),
                      trailing: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text('עלייה: ${row.top2Probability.toStringAsFixed(0)}%'),
                          Text(
                            '1 בבית: ${row.winGroupProbability.toStringAsFixed(0)}%',
                            style: theme.textTheme.bodySmall,
                          ),
                        ],
                      ),
                    ),
                    if (row != _groupStandings!.last) const Divider(height: 1),
                  ],
                ],
              ),
            ),
          ],
          const Divider(height: 32),
          Text('סיכויי אליפות', style: theme.textTheme.titleMedium),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: _loadingChampion ? null : _simulateChampion,
            icon: _loadingChampion
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Icon(Icons.emoji_events),
            label: Text(_loadingChampion ? 'מחשב...' : 'סמלץ מונדיאל'),
          ),
          if (_championOdds != null) ...[
            const SizedBox(height: 16),
            Card(
              child: Column(
                children: [
                  for (final row in _championOdds!.take(10)) ...[
                    ListTile(
                      title: Text(_shortName(row.team)),
                      trailing: Text(
                        '${row.probability.toStringAsFixed(1)}%',
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.bold,
                          color: theme.colorScheme.primary,
                        ),
                      ),
                    ),
                    if (row != _championOdds!.take(10).last) const Divider(height: 1),
                  ],
                ],
              ),
            ),
          ],
          if (_error != null) ...[
            const SizedBox(height: 16),
            Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
          ],
        ],
      ),
    );
  }
}
