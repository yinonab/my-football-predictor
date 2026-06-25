import '../models/market_tab_view_model.dart';
import '../models/prediction_result.dart';
import 'score_format.dart';

String marketStatusLabelHe(String status) {
  switch (status) {
    case 'זמין':
      return 'נתוני שוק זמינים';
    case 'אין יחסים למשחק':
      return 'אין יחסים לזוג נבחרות זה';
    case 'לא מחובר':
      return 'שוק לא מחובר בשרת';
    default:
      return status;
  }
}

String outcomeKeyLabelHe(String key) {
  switch (key) {
    case 'home_win':
      return 'ניצחון בית';
    case 'draw':
      return 'תיקו';
    case 'away_win':
      return 'ניצחון חוץ';
    default:
      return key;
  }
}

String formatProbPercent(double? value) {
  if (value == null) return '—';
  return '${value.toStringAsFixed(1)}%';
}

String formatDecimalOdds(double? value) {
  if (value == null || value <= 1) return '—';
  return value.toStringAsFixed(2);
}

String formatDelta(double? model, double? market) {
  if (model == null || market == null) return '—';
  final delta = model - market;
  final sign = delta > 0 ? '+' : '';
  return '$sign${delta.toStringAsFixed(1)}%';
}

String homeTeamShort(PredictionResult result) =>
    shortTeamName(result.homeTeam);

String awayTeamShort(PredictionResult result) =>
    shortTeamName(result.awayTeam);

List<String> buildMarketFootnotes(MarketTabViewModel vm) {
  final lines = <String>[
    'מצב שקלול: ${vm.blendModeLabel}',
  ];
  if (vm.oddsAffectPrediction) {
    lines.add(
      'משקלים מתוכננים: מודל ${vm.modelWeightPercent?.toStringAsFixed(0) ?? "70"}% · '
      'שוק ${vm.marketWeightPercent?.toStringAsFixed(0) ?? "30"}%',
    );
  }
  lines.addAll(vm.notes);
  return lines;
}
