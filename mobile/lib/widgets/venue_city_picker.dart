import 'package:flutter/material.dart';

import '../data/wc2026_host_venues.dart';

class VenueCityPicker extends StatelessWidget {
  final String? value;
  final ValueChanged<String?> onChanged;

  const VenueCityPicker({
    super.key,
    required this.value,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return InputDecorator(
      decoration: const InputDecoration(
        border: OutlineInputBorder(),
        labelText: 'עיר / אצטדיון אירוח (אופציונלי)',
      ),
      child: DropdownButtonHideUnderline(
        child: DropdownButton<String?>(
          value: value,
          isExpanded: true,
          hint: const Text('לא נבחר — ללא מזג אוויר / גובה אוטומטי'),
          items: [
            const DropdownMenuItem<String?>(
              value: null,
              child: Text('לא נבחר'),
            ),
            ...wc2026HostVenues.map(
              (v) => DropdownMenuItem<String?>(
                value: v.apiCity,
                child: Text(v.labelHe),
              ),
            ),
          ],
          onChanged: onChanged,
        ),
      ),
    );
  }
}
