import 'package:flutter/material.dart';

import '../utils/prediction_ui_copy.dart';
import '../utils/score_format.dart';
import '../models/prediction_result.dart';
import '../models/venue_mode.dart';
import '../services/api_service.dart';
import '../widgets/outcome_cards.dart';
import '../widgets/prediction_insight_sections.dart';
import '../widgets/score_list.dart';
import '../widgets/team_text_field.dart';
import '../widgets/venue_mode_selector.dart';
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
  final _teamAFocus = FocusNode();
  final _teamBFocus = FocusNode();

  PredictionSettings _settings = const PredictionSettings();
  List<String> _teams = [];
  VenueMode _venueMode = VenueMode.neutral;
  PredictionResult? _result;
  bool _serverOnline = false;
  bool _checking = true;
  bool _teamsLoading = false;
  bool _predicting = false;
  String? _error;
  String? _connectionError;

  @override
  void initState() {
    super.initState();
    _teamAController.addListener(_onTeamsChanged);
    _teamBController.addListener(_onTeamsChanged);
    _init();
  }

  void _onTeamsChanged() {
    if (_result != null && mounted) {
      setState(() => _result = null);
    }
  }

  void _onTeamAFocus() {
    _teamBFocus.unfocus();
  }

  void _onTeamBFocus() {
    _teamAFocus.unfocus();
  }

  @override
  void dispose() {
    _teamAController.dispose();
    _teamBController.dispose();
    _teamAFocus.dispose();
    _teamBFocus.dispose();
    super.dispose();
  }

  static const _startupHealthTimeout = Duration(seconds: 15);

  Future<void> _init() async {
    final settings = await _apiService.loadSettings();
    if (!mounted) return;
    setState(() {
      _settings = settings;
      _venueMode = settings.venueMode;
    });
    await _refreshConnection();
  }

  Future<void> _refreshConnection() async {
    await _checkServer();
    if (mounted && _serverOnline) {
      await _loadTeams();
    }
  }

  Future<void> _loadTeams() async {
    if (!mounted) return;
    setState(() => _teamsLoading = true);
    try {
      final teams = await _apiService.fetchTeams(_settings.apiBaseUrl);
      if (mounted) {
        setState(() {
          _teams = teams;
          _teamsLoading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _teamsLoading = false);
    }
  }

  Future<void> _checkServer() async {
    if (!mounted) return;
    setState(() {
      _checking = true;
      _connectionError = null;
    });
    final online = await _apiService.checkHealth(
      _settings.apiBaseUrl,
      timeout: _startupHealthTimeout,
    );
    if (!mounted) return;
    setState(() {
      _serverOnline = online;
      _checking = false;
      if (!online) {
        _connectionError =
            'לא ניתן להתחבר לשרת. משוך למטה לניסיון חוזר או בדוק את כתובת ה-API בהגדרות.';
      }
    });
  }

  Future<void> _predict() async {
    FocusScope.of(context).unfocus();

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
        settings: _settings.copyWith(venueMode: _venueMode),
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
        _venueMode = updated.venueMode;
      });
      await _refreshConnection();
    }
  }

  String _serverStatusLabel() {
    if (_checking) return 'מתחבר לשרת...';
    if (_serverOnline) {
      if (_teamsLoading) return 'שרת מחובר · טוען נבחרות...';
      return 'שרת מחובר · ${_teams.length} נבחרות';
    }
    return 'שרת לא מחובר';
  }

  String _predictButtonLabel() {
    if (_predicting) return 'מחשב...';
    if (_checking) return 'מתחבר לשרת...';
    if (!_serverOnline) return 'מחמם שרת...';
    return 'חזה משחק';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final useHostAwayLabels = _venueMode == VenueMode.firstTeamHome;
    final teamALabel = useHostAwayLabels ? 'נבחרת מארחת' : 'נבחרת א\'';
    final teamBLabel = useHostAwayLabels ? 'נבחרת אורחת' : 'נבחרת ב\'';
    const scoreLabelsNeutral = true;
    final showResults = _result != null && !_predicting;

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
        body: RefreshIndicator(
          onRefresh: _refreshConnection,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (_checking)
                    SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: theme.colorScheme.primary,
                      ),
                    )
                  else
                    Icon(
                      _serverOnline ? Icons.cloud_done : Icons.cloud_off,
                      color: _serverOnline ? Colors.green : Colors.red,
                      size: 18,
                    ),
                  const SizedBox(width: 6),
                  Text(
                    _serverStatusLabel(),
                    style: theme.textTheme.bodySmall,
                  ),
                ],
              ),
              if (_connectionError != null) ...[
                const SizedBox(height: 12),
                Card(
                  color: theme.colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(_connectionError!),
                        const SizedBox(height: 8),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton(
                            onPressed: _checking ? null : _refreshConnection,
                            child: const Text('נסה שוב'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
                    const SizedBox(height: 16),
                    TeamTextField(
                      label: teamALabel,
                      controller: _teamAController,
                      focusNode: _teamAFocus,
                      onFocusGained: _onTeamAFocus,
                      hint: 'Argentina (ארגנטינה)',
                      suggestions: _teams,
                      groupBadge: _result?.homeBreakdown.group,
                    ),
                    const SizedBox(height: 16),
                    TeamTextField(
                      label: teamBLabel,
                      controller: _teamBController,
                      focusNode: _teamBFocus,
                      onFocusGained: _onTeamBFocus,
                      hint: 'France (צרפת)',
                      suggestions: _teams,
                      groupBadge: _result?.awayBreakdown.group,
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'מיקום המשחק',
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                      textAlign: TextAlign.right,
                    ),
                    VenueModeSelector(
                      value: _venueMode,
                      team1: _teamAController.text.trim(),
                      team2: _teamBController.text.trim(),
                      onChanged: (mode) => setState(() => _venueMode = mode),
                    ),
                    if (showResults) ...[
                      Builder(
                        builder: (context) {
                          final note = hostAdvantageNote(
                            _result!.matchContextDiagnostics,
                          );
                          if (note == null) return const SizedBox.shrink();
                          return Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                              note,
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                              textAlign: TextAlign.right,
                            ),
                          );
                        },
                      ),
                    ],
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: FilledButton.icon(
                        onPressed: _predicting || _checking || !_serverOnline
                            ? null
                            : _predict,
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
                        label: Text(_predictButtonLabel()),
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
                    if (_predicting && _result != null) ...[
                      const SizedBox(height: 24),
                      const Center(child: LinearProgressIndicator()),
                      const SizedBox(height: 8),
                      Text(
                        'מחשב תחזית חדשה…',
                        style: theme.textTheme.bodySmall,
                        textAlign: TextAlign.center,
                      ),
                    ],
                    if (showResults) ...[
                      const SizedBox(height: 24),
                      Text(
                        'תוצאות חיזוי',
                        style: theme.textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.bold,
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '${shortTeamName(_result!.homeTeam)} נגד ${shortTeamName(_result!.awayTeam)}',
                        style: theme.textTheme.titleMedium?.copyWith(
                          color: theme.colorScheme.primary,
                          fontWeight: FontWeight.w600,
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      OutcomeCards(
                        probabilities: _result!.probabilities,
                        explanations: _result!.outcomeExplanations,
                        teamALabel: _result!.homeTeam,
                        teamBLabel: _result!.awayTeam,
                        isNeutralGround: scoreLabelsNeutral,
                      ),
                      const SizedBox(height: 12),
                      PredictionStatusBanner(result: _result!),
                      PredictionDataLimitBanner(result: _result!),
                      PredictionPrimaryScoreCard(
                        result: _result!,
                        isNeutralGround: scoreLabelsNeutral,
                      ),
                      if (_result!.scorelineDecision != null) ...[
                        const SizedBox(height: 8),
                        PredictionWhyCard(
                          result: _result!,
                          requestedVenueMode: _venueMode,
                        ),
                      ] else if (_result!.matchSummary.isNotEmpty) ...[
                        const SizedBox(height: 8),
                        PredictionWhyCard(
                          result: _result!,
                          requestedVenueMode: _venueMode,
                        ),
                      ],
                      if (_result!.h2hSummary.isNotEmpty) ...[
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
                      const SizedBox(height: 12),
                      ExpectedGoalsCard(result: _result!),
                      const SizedBox(height: 16),
                      Text(
                        'תוצאות אפשריות מובילות',
                        style: theme.textTheme.titleMedium,
                        textAlign: TextAlign.right,
                      ),
                      const SizedBox(height: 8),
                      ScoreList(
                        scores: _result!.topScores,
                        teamAName: _result!.homeTeam,
                        teamBName: _result!.awayTeam,
                        isNeutralGround: scoreLabelsNeutral,
                        initialVisibleCount: 3,
                      ),
                      const SizedBox(height: 12),
                      PredictionContextCard(
                        result: _result!,
                        requestedVenueMode: _venueMode,
                      ),
                      const SizedBox(height: 8),
                      PredictionTechnicalDetails(
                        result: _result!,
                        requestedVenueMode: _venueMode,
                        isNeutralGround: scoreLabelsNeutral,
                      ),
                    ],
              const SizedBox(height: 32),
            ],
          ),
        ),
      ),
    );
  }
}
