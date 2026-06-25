import 'package:flutter/material.dart';

import '../config/api_config.dart';
import '../models/prediction_result.dart';
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
  late TextEditingController _apiUrlController;
  late bool _oddsAffectPrediction;
  late bool _fusionBlowoutEnabled;
  late bool _useMatchContext;
  late bool _autoStadiumAltitude;
  bool _serverOnline = false;
  bool _checking = false;

  @override
  void initState() {
    super.initState();
    _apiUrlController = TextEditingController(text: widget.settings.apiBaseUrl);
    _oddsAffectPrediction = widget.settings.oddsAffectPrediction;
    _fusionBlowoutEnabled = widget.settings.fusionBlowoutEnabled;
    _useMatchContext = widget.settings.useMatchContext;
    _autoStadiumAltitude = widget.settings.autoStadiumAltitude;
    _checkServer();
  }

  @override
  void dispose() {
    _apiUrlController.dispose();
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
    final settings = widget.settings.copyWith(
      apiBaseUrl: _apiUrlController.text.trim(),
      oddsAffectPrediction: _oddsAffectPrediction,
      fusionBlowoutEnabled: _fusionBlowoutEnabled,
      useMatchContext: _useMatchContext,
      autoStadiumAltitude: _autoStadiumAltitude,
    );
    await widget.apiService.saveSettings(settings);
    if (mounted) Navigator.pop(context, settings);
  }

  @override
  Widget build(BuildContext context) {
    return Directionality(
      textDirection: TextDirection.rtl,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('הגדרות'),
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
            Text('חיזוי', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            SwitchListTile(
              title: const Text('שקול שוק הימורים בחיזוי'),
              subtitle: const Text(
                'מערבל את הסתברויות 1X2 של המודל עם קונצנזוס ספרי ההימורים '
                '(דורש THE_ODDS_API_KEY בשרת). לא משנה xG ישירות — רק את אחוזי הניצחון/תיקו.',
              ),
              value: _oddsAffectPrediction,
              onChanged: (v) => setState(() => _oddsAffectPrediction = v),
            ),
            SwitchListTile(
              title: const Text('תחזית גולנט משולבת'),
              subtitle: const Text(
                'כשהמועדף חזק (למשל 70%+ אחרי שילוב שוק), מעלה את xG של המועדף '
                'ומחשב מחדש את מטריצת התוצאות — כך 0-3, 0-4 וכו\' יופיעו במקום 0-2 בלבד. '
                'מומלץ להפעיל יחד עם "שקול שוק הימורים".',
              ),
              value: _fusionBlowoutEnabled,
              onChanged: (v) => setState(() => _fusionBlowoutEnabled = v),
            ),
            SwitchListTile(
              title: const Text('הקשר משחק ומזג אוויר'),
              subtitle: const Text(
                'מזג אוויר, מרחק נסיעה, מנוחה בין משחקים וגובה — מכוונים כוח קבוצה ו-xG '
                'לפי עיר האצטדיון ותאריך המשחק (נבחרים במסך הבית).',
              ),
              value: _useMatchContext,
              onChanged: (v) => setState(() => _useMatchContext = v),
            ),
            SwitchListTile(
              title: const Text('גובה אצטדיון אוטומטי'),
              subtitle: const Text(
                'כשלא הוזן גובה ידני, משתמש בגובה האצטדיון ממטא-דאטה מונדיאל 2026 '
                '(למשל מקסיקו סיטי) כדי להחיל עונש גובה על הקבוצה שאינה מורגלת.',
              ),
              value: _autoStadiumAltitude,
              onChanged: (v) => setState(() => _autoStadiumAltitude = v),
            ),
          ],
        ),
      ),
    );
  }
}
