String shortTeamName(String full) {
  final match = RegExp(r'\(([^)]+)\)').firstMatch(full);
  return match?.group(1) ?? full;
}

/// Avoid RTL mirroring of raw "2-1" into misleading "1-2".
String formatNamedScore(
  String raw, {
  required String teamAName,
  required String teamBName,
  bool isNeutralGround = true,
}) {
  final parts = raw.split('-');
  if (parts.length != 2) return raw;

  final homeGoals = parts[0].trim();
  final awayGoals = parts[1].trim();
  final teamA = shortTeamName(teamAName);
  final teamB = shortTeamName(teamBName);

  if (isNeutralGround) {
    return '$teamA $homeGoals–$awayGoals $teamB';
  }
  return '$teamA $homeGoals–$awayGoals $teamB';
}
