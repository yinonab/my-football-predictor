import '../models/prediction_result.dart';

bool shouldShowEnvironmentDataCard(PredictionResult result) {
  return result.environmentDiagnostics != null ||
      result.recentFormProviderDiagnostics != null;
}

String altitudeBucketLabelHe(String bucket) {
  switch (bucket) {
    case 'sea_level':
      return 'גובה ים';
    case 'low':
      return 'גובה נמוך';
    case 'moderate':
      return 'גובה בינוני';
    case 'high':
      return 'גובה גבוה';
    case 'very_high':
      return 'גובה גבוה מאוד';
    default:
      return 'לא ידוע';
  }
}

String weatherSourceLabelHe(String source) {
  switch (source) {
    case 'open-meteo':
      return 'Open-Meteo (תחזית)';
    case 'disabled':
      return 'כבוי (הקשר משחק)';
    case 'not_requested':
      return 'לא התבקש — בחר עיר אירוח';
    case 'unavailable':
      return 'לא זמין';
    default:
      return source;
  }
}

String weatherAdjustmentModeLabelHe(String mode) {
  switch (mode) {
    case 'active_existing':
      return 'פעיל בחיזוי (מזג אוויר קיים)';
    case 'shadow_only':
      return 'אבחון בלבד (לא מוחל)';
    case 'disabled':
      return 'כבוי';
    case 'unavailable':
      return 'לא זמין';
    case 'none':
      return 'ללא השפעה';
    default:
      return mode;
  }
}

String recentFormProviderLabelHe(String provider) {
  switch (provider) {
    case 'sofascore_recent_form':
      return 'Sofascore (קאש)';
    case 'static/offline fallback':
      return 'נתונים סטטיים / offline';
    case 'football_data_recent_form':
      return 'Football-Data';
    case 'api_football_recent_form':
      return 'API-Football';
    case 'unavailable':
      return 'לא זמין';
    default:
      return provider;
  }
}

List<String> buildEnvironmentSummaryLines(PredictionResult result) {
  final lines = <String>[];
  final env = result.environmentDiagnostics;
  final rf = result.recentFormProviderDiagnostics;

  if (env != null) {
    if (env.venueStadium != null || env.venueCity != null) {
      final parts = <String>[];
      if (env.venueStadium != null) parts.add(env.venueStadium!);
      if (env.venueCity != null && env.venueCity != env.venueStadium) {
        parts.add(env.venueCity!);
      }
      lines.add('אצטדיון: ${parts.join(' · ')}');
    }
    if (env.venueAltitudeM != null) {
      lines.add(
        'גובה: ${env.venueAltitudeM} מ\' (${altitudeBucketLabelHe(env.altitudeBucket)})',
      );
    }
    if (env.manualAltitudeApplied) {
      lines.add(
        'גובה ידני בחישוב: ${env.requestAltitudeM} מ\' (מעל ${env.activeAltitudeThresholdM} מ\')',
      );
    } else if (env.shadowAltitudePowerMultiplier != null &&
        env.shadowAltitudePowerMultiplier! < 1.0) {
      lines.add(
        'גובה אצטדיון — אבחון בלבד (השפעה אפשרית עתידית: '
        '${((1 - env.shadowAltitudePowerMultiplier!) * 100).toStringAsFixed(0)}%)',
      );
    }
    if (env.temperatureC != null || env.precipitationMm != null) {
      final wParts = <String>[];
      if (env.temperatureC != null) {
        wParts.add('${env.temperatureC!.toStringAsFixed(1)}°C');
      }
      if (env.precipitationMm != null) {
        wParts.add('גשם ~${env.precipitationMm!.toStringAsFixed(1)} מ"מ');
      }
      lines.add('מזג אוויר: ${wParts.join(' · ')}');
    } else if (env.weatherSource == 'not_requested') {
      lines.add('מזג אוויר: בחר עיר אירוח לקבלת תחזית');
    }
    lines.add('מקור מזג אוויר: ${weatherSourceLabelHe(env.weatherSource)}');
    lines.add(
      'מצב מזג אוויר: ${weatherAdjustmentModeLabelHe(env.weatherAdjustmentMode)}',
    );
    if (env.weatherSummary != null && env.weatherSummary!.isNotEmpty) {
      lines.add(env.weatherSummary!);
    }
    for (final note in env.environmentNotes) {
      lines.add(note);
    }
  }

  if (rf != null) {
    lines.add(
      'כושר אחרון: ${recentFormProviderLabelHe(rf.primaryProvider)}',
    );
    if (rf.cacheLastUpdatedUtc != null) {
      lines.add('עדכון קאש: ${rf.cacheLastUpdatedUtc}');
    }
    final sofa = rf.sourceMix['sofascore_recent_form'];
    if (sofa != null && sofa > 0) {
      lines.add('שורות Sofascore בחלון last-10: $sofa');
    }
    for (final note in rf.providerNotes) {
      lines.add(note);
    }
  }

  return lines;
}
