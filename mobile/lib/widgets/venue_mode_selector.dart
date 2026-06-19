import 'package:flutter/material.dart';

import '../models/venue_mode.dart';
import '../utils/score_format.dart';

class VenueModeSelector extends StatelessWidget {
  final VenueMode value;
  final ValueChanged<VenueMode> onChanged;
  final String team1;
  final String team2;

  const VenueModeSelector({
    super.key,
    required this.value,
    required this.onChanged,
    required this.team1,
    required this.team2,
  });

  String get _team1Label =>
      team1.isEmpty ? 'הנבחרת הראשונה' : shortTeamName(team1);

  String get _team2Label =>
      team2.isEmpty ? 'הנבחרת השנייה' : shortTeamName(team2);

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _option(
          context,
          theme: theme,
          mode: VenueMode.neutral,
          title: 'מגרש ניטרלי',
          subtitle: 'אין יתרון ביתיות לאף נבחרת',
        ),
        _option(
          context,
          theme: theme,
          mode: VenueMode.firstTeamHome,
          title: 'הנבחרת הראשונה מארחת',
          subtitle: '$_team1Label מקבלת יתרון ביתיות',
        ),
        _option(
          context,
          theme: theme,
          mode: VenueMode.secondTeamHome,
          title: 'הנבחרת השנייה מארחת',
          subtitle: '$_team2Label מקבלת יתרון ביתיות',
        ),
        _option(
          context,
          theme: theme,
          mode: VenueMode.hostCountryAuto,
          title: 'זיהוי אוטומטי לפי מדינה מארחת (ניסיוני)',
          subtitle:
              'אם המדינה המארחת מזוהה, המודל יוסיף יתרון לנבחרת הביתית',
        ),
      ],
    );
  }

  Widget _option(
    BuildContext context, {
    required ThemeData theme,
    required VenueMode mode,
    required String title,
    required String subtitle,
  }) {
    return RadioListTile<VenueMode>(
      contentPadding: EdgeInsets.zero,
      value: mode,
      groupValue: value,
      onChanged: (v) {
        if (v != null) onChanged(v);
      },
      title: Text(
        title,
        style: theme.textTheme.bodyLarge,
        textAlign: TextAlign.right,
      ),
      subtitle: Text(
        subtitle,
        style: theme.textTheme.bodySmall?.copyWith(
          color: theme.colorScheme.onSurfaceVariant,
        ),
        textAlign: TextAlign.right,
      ),
    );
  }
}
