import 'package:flutter/material.dart';

import '../models/prediction_result.dart';
import '../services/api_service.dart';
import '../widgets/outcome_cards.dart';
import '../widgets/score_list.dart';
import '../widgets/team_text_field.dart';
import 'settings_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _apiService = ApiService();
  final _teamAController = TextEditingController();
  final _teamBController = TextEditingController();

  PredictionSettings _settings = const PredictionSettings();
  List<String> _teams = [];
  bool _neutralGround = true;
  PredictionResult? _result;
  bool _serverOnline = false;
  bool _checking = true;
  bool _predicting = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _init();
  }

  @override
  void dispose() {
    _teamAController.dispose();
    _teamBController.dispose();
    super.dispose();
  }

  Future<void> _init() async {
    _settings = await _apiService.loadSettings();
    _neutralGround = _settings.neutralGround;
    await _checkServer();
    if (_serverOnline) {
      await _loadTeams();
    }
  }

  Future<void> _loadTeams() async {
    try {
      final teams = await _apiService.fetchTeams(_settings.apiBaseUrl);
      if (mounted) setState(() => _teams = teams);
    } catch (_) {}
  }

  Future<void> _checkServer() async {
    setState(() {
      _checking = true;
      _error = null;
    });
    final online = await _apiService.checkHealth(_settings.apiBaseUrl);
    if (!mounted) return;
    setState(() {
      _serverOnline = online;
      _checking = false;
      if (!online) {
        _error = 'לא ניתן להתחבר לשרת. בדוק את כתובת ה-API בהגדרות.';
      }
    });
  }

  Future<void> _predict() async {
    final teamA = _teamAController.text.trim();
    final teamB = _teamBController.text.trim();

    if (teamA.isEmpty || teamB.isEmpty) {
      setState(() => _error = 'יש להזין שם לשתי הנבחרות');
      return;
    }
    if (teamA == teamB) {
      setState(() => _error = 'יש להזין שתי נבחרות שונות');
      return;
    }

    setState(() {
      _predicting = true;
      _error = null;
    });

    try {
      final result = await _apiService.predict(
        baseUrl: _settings.apiBaseUrl,
        homeTeam: teamA,
        awayTeam: teamB,
        settings: _settings.copyWith(neutralGround: _neutralGround),
      );
      if (!mounted) return;
      setState(() {
        _result = result;
        _predicting = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        _predicting = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'שגיאה בחיזוי. ודא שהשרת פועל.';
        _predicting = false;
      });
    }
  }

  Future<void> _openSettings() async {
    final updated = await Navigator.push<PredictionSettings>(
      context,
      MaterialPageRoute(
        builder: (_) => SettingsScreen(
          settings: _settings,
          apiService: _apiService,
        ),
      ),
    );
    if (updated != null) {
      setState(() {
        _settings = updated;
        _neutralGround = updated.neutralGround;
      });
      await _checkServer();
      if (_serverOnline) await _loadTeams();
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final teamALabel = _neutralGround ? 'נבחרת א\'' : 'נבחרת מארחת';
    final teamBLabel = _neutralGround ? 'נבחרת ב\'' : 'נבחרת אורחת';

    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('חיזוי משחק'),
          actions: [
            IconButton(
              icon: const Icon(Icons.settings),
              onPressed: _openSettings,
              tooltip: 'הגדרות',
            ),
          ],
        ),
        body: _checking
            ? const Center(child: CircularProgressIndicator())
            : RefreshIndicator(
                onRefresh: () async {
                  await _checkServer();
                  if (_serverOnline) await _loadTeams();
                },
                child: ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          _serverOnline ? Icons.cloud_done : Icons.cloud_off,
                          color: _serverOnline ? Colors.green : Colors.red,
                          size: 18,
                        ),
                        const SizedBox(width: 6),
                        Text(
                          _serverOnline
                              ? 'שרת מחובר · ${_teams.length} נבחרות'
                              : 'שרת לא מחובר',
                          style: theme.textTheme.bodySmall,
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    TeamTextField(
                      label: teamALabel,
                      controller: _teamAController,
                      hint: 'Argentina (ארגנטינה)',
                      suggestions: _teams,
                      groupBadge: _result?.homeBreakdown.group,
                    ),
                    const SizedBox(height: 16),
                    TeamTextField(
                      label: teamBLabel,
                      controller: _teamBController,
                      hint: 'France (צרפת)',
                      suggestions: _teams,
                      groupBadge: _result?.awayBreakdown.group,
                    ),
                    const SizedBox(height: 12),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: const Text('משחק במגרש ניטרלי'),
                      value: _neutralGround,
                      onChanged: (v) => setState(() => _neutralGround = v),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: FilledButton.icon(
                        onPressed: _predicting || !_serverOnline ? null : _predict,
                        icon: _predicting
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: Colors.white,
                                ),
                              )
                            : const Icon(Icons.sports_soccer),
                        label: Text(_predicting ? 'מחשב...' : 'חזה משחק'),
                      ),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 16),
                      Card(
                        color: theme.colorScheme.errorContainer,
                        child: Padding(
                          padding: const EdgeInsets.all(12),
                          child: Text(_error!),
                        ),
                      ),
                    ],
                    if (_result != null) ...[
                      const SizedBox(height: 32),
                      Text(
                        'תוצאות חיזוי',
                        style: theme.textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      OutcomeCards(
                        probabilities: _result!.probabilities,
                        explanations: _result!.outcomeExplanations,
                        teamALabel: _result!.homeTeam,
                        teamBLabel: _result!.awayTeam,
                        isNeutralGround: _neutralGround,
                      ),
                      if (_result!.matchSummary.isNotEmpty) ...[
                        const SizedBox(height: 12),
                        Card(
                          color: theme.colorScheme.surfaceContainerHighest,
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Text(
                              _result!.matchSummary,
                              style: theme.textTheme.bodyMedium,
                              textAlign: TextAlign.right,
                            ),
                          ),
                        ),
                      ],
                      if (_result!.h2hSummary.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        Card(
                          color: theme.colorScheme.secondaryContainer.withValues(alpha: 0.4),
                          child: Padding(
                            padding: const EdgeInsets.all(12),
                            child: Row(
                              children: [
                                Icon(Icons.history, size: 20, color: theme.colorScheme.secondary),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    _result!.h2hSummary,
                                    style: theme.textTheme.bodyMedium,
                                    textAlign: TextAlign.right,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                      if (_result!.matchContext?.hasDetails == true) ...[
                        const SizedBox(height: 8),
                        Card(
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
                                if (_result!.matchContext!.weatherSummary != null) ...[
                                  const SizedBox(height: 8),
                                  Text(
                                    _result!.matchContext!.weatherSummary!,
                                    style: theme.textTheme.bodyMedium,
                                    textAlign: TextAlign.right,
                                  ),
                                ],
                                if (_result!.matchContext!.homeRestDays != null ||
                                    _result!.matchContext!.awayRestDays != null) ...[
                                  const SizedBox(height: 6),
                                  Text(
                                    'מנוחה: בית ${_result!.matchContext!.homeRestDays ?? "—"} ימים · '
                                    'חוץ ${_result!.matchContext!.awayRestDays ?? "—"} ימים',
                                    style: theme.textTheme.bodySmall,
                                    textAlign: TextAlign.right,
                                  ),
                                ],
                                if (_result!.matchContext!.awayTravelKm != null &&
                                    _result!.matchContext!.awayTravelKm! >= 2000) ...[
                                  const SizedBox(height: 4),
                                  Text(
                                    'נסיעת חוץ: ${_result!.matchContext!.awayTravelKm!.toStringAsFixed(0)} ק"מ',
                                    style: theme.textTheme.bodySmall,
                                    textAlign: TextAlign.right,
                                  ),
                                ],
                                if (_result!.matchContext!.notes.isNotEmpty) ...[
                                  const SizedBox(height: 8),
                                  ..._result!.matchContext!.notes.map(
                                    (n) => Padding(
                                      padding: const EdgeInsets.only(bottom: 4),
                                      child: Text(
                                        '• $n',
                                        style: theme.textTheme.bodySmall?.copyWith(
                                          color: theme.colorScheme.onSurfaceVariant,
                                        ),
                                        textAlign: TextAlign.right,
                                      ),
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ),
                        ),
                      ],
                      const SizedBox(height: 16),
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            children: [
                              Text('xG צפוי', style: theme.textTheme.titleSmall),
                              const SizedBox(height: 8),
                              Text(
                                '${_shortName(_result!.homeTeam)}: ${_result!.homeXg}  |  '
                                '${_shortName(_result!.awayTeam)}: ${_result!.awayXg}',
                                style: theme.textTheme.titleMedium?.copyWith(
                                  fontWeight: FontWeight.w600,
                                ),
                                textAlign: TextAlign.center,
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Card(
                        color: theme.colorScheme.primaryContainer.withValues(alpha: 0.35),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(
                                'טווח תוצאות (${_result!.scoreCoverage.achievedPercent.toStringAsFixed(0)}% מהמסה)',
                                style: theme.textTheme.titleSmall,
                                textAlign: TextAlign.right,
                              ),
                              const SizedBox(height: 8),
                              Wrap(
                                spacing: 8,
                                runSpacing: 8,
                                alignment: WrapAlignment.end,
                                children: _result!.scoreCoverage.scores
                                    .map(
                                      (s) => Chip(
                                        label: Text(s),
                                        backgroundColor:
                                            theme.colorScheme.surface,
                                      ),
                                    )
                                    .toList(),
                              ),
                              if (_result!.scoreCoverage.explanation.isNotEmpty) ...[
                                const SizedBox(height: 8),
                                Text(
                                  _result!.scoreCoverage.explanation,
                                  style: theme.textTheme.bodySmall?.copyWith(
                                    color: theme.colorScheme.onSurfaceVariant,
                                  ),
                                  textAlign: TextAlign.right,
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'תחזית מדויקת — 3 האפשרויות המובילות',
                        style: theme.textTheme.titleMedium,
                        textAlign: TextAlign.right,
                      ),
                      const SizedBox(height: 8),
                      ScoreList(
                        scores: _result!.topScores,
                        teamAName: _result!.homeTeam,
                        teamBName: _result!.awayTeam,
                        isNeutralGround: _neutralGround,
                      ),
                      const SizedBox(height: 16),
                      ExpansionTile(
                        title: const Text('פירוט כוח נבחרות'),
                        children: [
                          ListTile(
                            title: Text(_result!.homeBreakdown.name),
                            subtitle: Text(_result!.homeBreakdown.breakdown),
                            trailing: Text(_result!.homePower.toStringAsFixed(0)),
                          ),
                          ListTile(
                            title: Text(_result!.awayBreakdown.name),
                            subtitle: Text(_result!.awayBreakdown.breakdown),
                            trailing: Text(_result!.awayPower.toStringAsFixed(0)),
                          ),
                        ],
                      ),
                    ],
                    const SizedBox(height: 32),
                  ],
                ),
              ),
      ),
    );
  }

  String _shortName(String full) {
    final match = RegExp(r'\(([^)]+)\)').firstMatch(full);
    return match?.group(1) ?? full;
  }
}
