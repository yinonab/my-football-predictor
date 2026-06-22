import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../config/api_config.dart';
import '../models/prediction_result.dart';
import '../models/venue_mode.dart';

class ApiException implements Exception {
  final String message;
  final int? statusCode;

  const ApiException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

class ApiService {
  static bool isLocalDevUrl(String url) {
    final lower = url.toLowerCase();
    return lower.contains('10.0.2.2') ||
        lower.contains('127.0.0.1') ||
        lower.contains('localhost');
  }

  Future<PredictionSettings> loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    var apiUrl = prefs.getString('apiBaseUrl') ?? defaultBaseUrl();

    // Physical devices: migrate old emulator/localhost URLs to production server.
    if (!kIsWeb && isLocalDevUrl(apiUrl)) {
      apiUrl = productionApiUrl;
      await prefs.setString('apiBaseUrl', apiUrl);
    }

    if (kIsWeb) {
      apiUrl = await _resolveWorkingUrl(apiUrl);
    }

    final venueModeStr = prefs.getString('venueMode');
    VenueMode venueMode;
    if (venueModeStr != null) {
      venueMode = VenueModeApi.fromApi(venueModeStr) ?? VenueMode.neutral;
    } else {
      final neutralGround = prefs.getBool('neutralGround') ?? true;
      venueMode = venueModeFromNeutralGround(neutralGround);
    }

    return PredictionSettings(
      rho: prefs.getDouble('rho') ?? -0.15,
      avgGoals: prefs.getDouble('avgGoals') ?? 2.6,
      homeAdvantage: prefs.getDouble('homeAdvantage') ?? 0,
      alpha: prefs.getDouble('alpha') ?? 0.0,
      altitude: prefs.getInt('altitude') ?? 0,
      starAbsent: prefs.getBool('starAbsent') ?? false,
      awayStarAbsent: prefs.getBool('awayStarAbsent') ?? false,
      venueMode: venueMode,
      useLiveStats: prefs.getBool('useLiveStats') ?? false,
      apiBaseUrl: apiUrl,
    );
  }

  Future<void> saveSettings(PredictionSettings settings) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setDouble('rho', settings.rho);
    await prefs.setDouble('avgGoals', settings.avgGoals);
    await prefs.setDouble('homeAdvantage', settings.homeAdvantage);
    await prefs.setDouble('alpha', settings.alpha);
    await prefs.setInt('altitude', settings.altitude);
    await prefs.setBool('starAbsent', settings.starAbsent);
    await prefs.setBool('awayStarAbsent', settings.awayStarAbsent);
    await prefs.setString('venueMode', settings.venueMode.apiValue);
    await prefs.setBool('neutralGround', settings.neutralGround);
    await prefs.setBool('useLiveStats', settings.useLiveStats);
    await prefs.setString('apiBaseUrl', settings.apiBaseUrl);
  }

  static String defaultBaseUrl() {
    if (kIsWeb) return 'http://127.0.0.1:8000';
    return productionApiUrl;
  }

  Duration _timeoutFor(String baseUrl, {int seconds = 10}) {
    if (baseUrl.contains('onrender.com')) {
      return const Duration(seconds: 90);
    }
    return Duration(seconds: seconds);
  }

  Future<String> _resolveWorkingUrl(String preferred) async {
    final candidates = {
      preferred,
      'http://127.0.0.1:8000',
      'http://127.0.0.1:8001',
      'http://localhost:8000',
      'http://localhost:8001',
    };
    for (final url in candidates) {
      if (await checkHealth(url)) return url;
    }
    return preferred;
  }

  Future<bool> checkHealth(String baseUrl, {Duration? timeout}) async {
    final effectiveTimeout = timeout ?? _timeoutFor(baseUrl, seconds: 5);
    try {
      final response = await http
          .get(Uri.parse('$baseUrl/api/health'))
          .timeout(effectiveTimeout);
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<List<String>> fetchTeams(String baseUrl) async {
    final response = await http
        .get(Uri.parse('$baseUrl/api/teams'))
        .timeout(_timeoutFor(baseUrl));

    if (response.statusCode != 200) {
      throw ApiException('שגיאה בטעינת נבחרות', statusCode: response.statusCode);
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return List<String>.from(data['teams'] as List<dynamic>);
  }

  Future<Map<String, List<Map<String, dynamic>>>> fetchGroups(
    String baseUrl,
  ) async {
    final response = await http
        .get(Uri.parse('$baseUrl/api/groups'))
        .timeout(_timeoutFor(baseUrl));

    if (response.statusCode != 200) {
      throw ApiException('שגיאה בטעינת בתים', statusCode: response.statusCode);
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    final groups = data['groups'] as Map<String, dynamic>;
    return groups.map(
      (key, value) => MapEntry(
        key,
        List<Map<String, dynamic>>.from(value as List<dynamic>),
      ),
    );
  }

  Future<PredictionResult> predict({
    required String baseUrl,
    required String homeTeam,
    required String awayTeam,
    required PredictionSettings settings,
  }) async {
    final body = jsonEncode(
      buildPredictRequestBody(
        homeTeam: homeTeam,
        awayTeam: awayTeam,
        venueMode: settings.venueMode,
        rho: settings.rho,
        avgGoals: settings.avgGoals,
        homeAdvantage: settings.homeAdvantage,
        alpha: settings.alpha,
        altitude: settings.altitude,
        starAbsent: settings.starAbsent,
        awayStarAbsent: settings.awayStarAbsent,
        useLiveStats: settings.useLiveStats,
      ),
    );

    final response = await http
        .post(
          Uri.parse('$baseUrl/api/predict'),
          headers: {'Content-Type': 'application/json'},
          body: body,
        )
        .timeout(_timeoutFor(baseUrl, seconds: 15));

    if (response.statusCode == 400 || response.statusCode == 404) {
      final error = jsonDecode(response.body) as Map<String, dynamic>;
      throw ApiException(error['detail']?.toString() ?? 'שגיאת בקשה');
    }

    if (response.statusCode != 200) {
      throw ApiException(
        'שגיאת שרת (${response.statusCode})',
        statusCode: response.statusCode,
      );
    }

    return PredictionResult.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  Future<List<GroupStanding>> simulateGroup({
    required String baseUrl,
    required String group,
    int iterations = 500,
  }) async {
    final body = jsonEncode({'group': group, 'iterations': iterations});
    final response = await http
        .post(
          Uri.parse('$baseUrl/api/simulate/group'),
          headers: {'Content-Type': 'application/json'},
          body: body,
        )
        .timeout(_timeoutFor(baseUrl, seconds: 120));

    if (response.statusCode != 200) {
      throw ApiException('שגיאה בסימולציית בית', statusCode: response.statusCode);
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return (data['standings'] as List<dynamic>)
        .map((e) => GroupStanding.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<List<ChampionOdds>> simulateChampion({
    required String baseUrl,
    int iterations = 1000,
  }) async {
    final body = jsonEncode({'iterations': iterations});
    final response = await http
        .post(
          Uri.parse('$baseUrl/api/simulate/champion'),
          headers: {'Content-Type': 'application/json'},
          body: body,
        )
        .timeout(_timeoutFor(baseUrl, seconds: 180));

    if (response.statusCode != 200) {
      throw ApiException('שגיאה בסימולציית אליפות', statusCode: response.statusCode);
    }

    final data = jsonDecode(response.body) as Map<String, dynamic>;
    return (data['champion_odds'] as List<dynamic>)
        .map((e) => ChampionOdds.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<Map<String, dynamic>> updateElo({
    required String baseUrl,
    required String homeTeam,
    required String awayTeam,
    required int homeGoals,
    required int awayGoals,
    bool neutralGround = true,
    bool recordMatch = true,
  }) async {
    final body = jsonEncode({
      'home_team': homeTeam,
      'away_team': awayTeam,
      'home_goals': homeGoals,
      'away_goals': awayGoals,
      'neutral_ground': neutralGround,
      'record_match': recordMatch,
    });

    final response = await http
        .post(
          Uri.parse('$baseUrl/api/elo/update'),
          headers: {'Content-Type': 'application/json'},
          body: body,
        )
        .timeout(_timeoutFor(baseUrl, seconds: 30));

    if (response.statusCode != 200) {
      final error = jsonDecode(response.body) as Map<String, dynamic>;
      throw ApiException(error['detail']?.toString() ?? 'שגיאת עדכון Elo');
    }

    return jsonDecode(response.body) as Map<String, dynamic>;
  }
}
