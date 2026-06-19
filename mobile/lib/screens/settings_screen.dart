import 'package:flutter/material.dart';

import '../config/api_config.dart';
import '../models/prediction_result.dart';
import '../models/venue_mode.dart';
import '../services/api_service.dart';

class SettingsScreen extends StatefulWidget {
  final PredictionSettings settings;
  final ApiService apiService;

  const SettingsScreen({
    super.key,
    required this.settings,
    required this.apiService,
  });

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  late double _rho;
  late double _avgGoals;
  late double _homeAdvantage;
  late double _alpha;
  late int _altitude;
  late bool _starAbsent;
  late bool _awayStarAbsent;
  late bool _neutralGround;
  late bool _useLiveStats;
  late TextEditingController _apiUrlController;
  bool _serverOnline = false;
  bool _checking = false;
  final _eloHomeController = TextEditingController();
  final _eloAwayController = TextEditingController();
  final _homeGoalsController = TextEditingController(text: '0');
  final _awayGoalsController = TextEditingController(text: '0');
  String? _eloMessage;
  bool _eloUpdating = false;

  @override
  void initState() {
    super.initState();
    _rho = widget.settings.rho;
    _avgGoals = widget.settings.avgGoals;
    _homeAdvantage = widget.settings.homeAdvantage;
    _alpha = widget.settings.alpha;
    _altitude = widget.settings.altitude;
    _starAbsent = widget.settings.starAbsent;
    _awayStarAbsent = widget.settings.awayStarAbsent;
    _neutralGround = widget.settings.neutralGround;
    _useLiveStats = widget.settings.useLiveStats;
    _apiUrlController = TextEditingController(text: widget.settings.apiBaseUrl);
    _checkServer();
  }

  @override
  void dispose() {
    _apiUrlController.dispose();
    _eloHomeController.dispose();
    _eloAwayController.dispose();
    _homeGoalsController.dispose();
    _awayGoalsController.dispose();
    super.dispose();
  }

  Future<void> _checkServer() async {
    setState(() => _checking = true);
    final online = await widget.apiService.checkHealth(_apiUrlController.text.trim());
    if (mounted) {
      setState(() {
        _serverOnline = online;
        _checking = false;
      });
    }
  }

  Future<void> _save() async {
    final settings = PredictionSettings(
      rho: _rho,
      avgGoals: _avgGoals,
      homeAdvantage: _homeAdvantage,
      alpha: _alpha,
      altitude: _altitude,
      starAbsent: _starAbsent,
      awayStarAbsent: _awayStarAbsent,
      venueMode: venueModeFromNeutralGround(_neutralGround),
      useLiveStats: _useLiveStats,
      apiBaseUrl: _apiUrlController.text.trim(),
    );
    await widget.apiService.saveSettings(settings);
    if (mounted) Navigator.pop(context, settings);
  }

  Future<void> _submitMatchResult() async {
    final home = _eloHomeController.text.trim();
    final away = _eloAwayController.text.trim();
    if (home.isEmpty || away.isEmpty) {
      setState(() => _eloMessage = 'יש להזין שמות נבחרות');
      return;
    }
    setState(() {
      _eloUpdating = true;
      _eloMessage = null;
    });
    try {
      final result = await widget.apiService.updateElo(
        baseUrl: _apiUrlController.text.trim(),
        homeTeam: home,
        awayTeam: away,
        homeGoals: int.tryParse(_homeGoalsController.text) ?? 0,
        awayGoals: int.tryParse(_awayGoalsController.text) ?? 0,
        neutralGround: _neutralGround,
      );
      if (mounted) {
        setState(() {
          _eloMessage =
              'עודכן: ${result['home_team']} ${result['home_elo_after']} | '
              '${result['away_team']} ${result['away_elo_after']} '
              '(${result['live_match_count']} משחקים שמורים)';
        });
      }
    } on ApiException catch (e) {
      if (mounted) setState(() => _eloMessage = e.message);
    } catch (_) {
      if (mounted) setState(() => _eloMessage = 'שגיאת רשת');
    } finally {
      if (mounted) setState(() => _eloUpdating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('הגדרות מתקדמות'),
          actions: [
            TextButton(onPressed: _save, child: const Text('שמור')),
          ],
        ),
        body: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text('חיבור לשרת', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            TextField(
              controller: _apiUrlController,
              textAlign: TextAlign.left,
              textDirection: TextDirection.ltr,
              decoration: InputDecoration(
                labelText: 'כתובת API',
                suffixIcon: _checking
                    ? const Padding(
                        padding: EdgeInsets.all(12),
                        child: SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                      )
                    : Icon(
                        _serverOnline ? Icons.cloud_done : Icons.cloud_off,
                        color: _serverOnline ? Colors.green : Colors.red,
                      ),
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _checkServer,
              icon: const Icon(Icons.refresh),
              label: const Text('בדוק חיבור'),
            ),
            if (ApiService.isLocalDevUrl(_apiUrlController.text))
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  'כתובת מקומית לא עובדת בטלפון — השתמש בשרת Render',
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            TextButton.icon(
              onPressed: () {
                setState(() => _apiUrlController.text = productionApiUrl);
                _checkServer();
              },
              icon: const Icon(Icons.cloud),
              label: const Text('החלף לשרת Render'),
            ),
            const Divider(height: 32),
            Text('פרמטרי מודל (כיול WC 2018–2026)', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () {
                setState(() {
                  _rho = -0.15;
                  _avgGoals = 2.6;
                  _homeAdvantage = 0;
                  _alpha = 0.0;
                  _neutralGround = true;
                  _apiUrlController.text = productionApiUrl;
                });
                _checkServer();
              },
              icon: const Icon(Icons.restore),
              label: const Text('איפוס לערכי כיול'),
            ),
            const SizedBox(height: 16),
            Text('Dixon-Coles (ρ): ${_rho.toStringAsFixed(2)}'),
            Slider(value: _rho, min: -0.15, max: 0, divisions: 15, onChanged: (v) => setState(() => _rho = v)),
            Text('ממוצע שערים: ${_avgGoals.toStringAsFixed(1)}'),
            Slider(value: _avgGoals, min: 1.5, max: 3.5, divisions: 20, onChanged: (v) => setState(() => _avgGoals = v)),
            Text('Overdispersion (α): ${_alpha.toStringAsFixed(2)}'),
            Slider(value: _alpha, min: 0, max: 0.3, divisions: 15, onChanged: (v) => setState(() => _alpha = v)),
            Text('יתרון ביתיות: ${_homeAdvantage.toInt()}'),
            Slider(value: _homeAdvantage, min: 0, max: 150, divisions: 15, onChanged: (v) => setState(() => _homeAdvantage = v)),
            SwitchListTile(
              title: const Text('מגרש ניטרלי'),
              value: _neutralGround,
              onChanged: (v) => setState(() => _neutralGround = v),
            ),
            SwitchListTile(
              title: const Text('נתונים חיים (API-Football)'),
              subtitle: const Text('API_FOOTBALL_KEY בשרת'),
              value: _useLiveStats,
              onChanged: (v) => setState(() => _useLiveStats = v),
            ),
            const Divider(height: 32),
            Text('תוצאת משחק אמיתית (מונדיאל)', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            Text(
              'מעדכן Elo, שומר משחק ומחשב מחדש דירוגים',
              style: Theme.of(context).textTheme.bodySmall,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _eloHomeController,
              decoration: const InputDecoration(
                labelText: 'נבחרת א\' (בית)',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _eloAwayController,
              decoration: const InputDecoration(
                labelText: 'נבחרת ב\' (חוץ)',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _homeGoalsController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'שערים א\'',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextField(
                    controller: _awayGoalsController,
                    keyboardType: TextInputType.number,
                    decoration: const InputDecoration(
                      labelText: 'שערים ב\'',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _eloUpdating || !_serverOnline ? null : _submitMatchResult,
              icon: _eloUpdating
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                    )
                  : const Icon(Icons.save),
              label: Text(_eloUpdating ? 'שומר...' : 'שמור תוצאה + עדכן Elo'),
            ),
            if (_eloMessage != null) ...[
              const SizedBox(height: 8),
              Text(
                _eloMessage!,
                style: TextStyle(
                  color: _eloMessage!.startsWith('עודכן')
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).colorScheme.error,
                ),
              ),
            ],
            const Divider(height: 32),
            Text('תיקונים ידניים', style: Theme.of(context).textTheme.titleMedium),
            Text('גובה: $_altitude מ\''),
            Slider(value: _altitude.toDouble(), min: 0, max: 3000, divisions: 30, onChanged: (v) => setState(() => _altitude = v.round())),
            SwitchListTile(
              title: const Text('שחקן מפתח חסר — נבחרת א\''),
              value: _starAbsent,
              onChanged: (v) => setState(() => _starAbsent = v),
            ),
            SwitchListTile(
              title: const Text('שחקן מפתח חסר — נבחרת ב\''),
              value: _awayStarAbsent,
              onChanged: (v) => setState(() => _awayStarAbsent = v),
            ),
          ],
        ),
      ),
    );
  }
}
