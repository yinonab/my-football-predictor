import 'package:flutter/material.dart';

class TeamTextField extends StatelessWidget {
  final String label;
  final TextEditingController controller;
  final String? hint;
  final List<String> suggestions;
  final String? groupBadge;

  const TeamTextField({
    super.key,
    required this.label,
    required this.controller,
    this.hint,
    this.suggestions = const [],
    this.groupBadge,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            if (groupBadge != null)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: theme.colorScheme.secondaryContainer,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  'בית $groupBadge',
                  style: theme.textTheme.labelMedium,
                ),
              )
            else
              const SizedBox.shrink(),
            Text(
              label,
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.right,
            ),
          ],
        ),
        const SizedBox(height: 8),
        Autocomplete<String>(
          initialValue: TextEditingValue(text: controller.text),
          optionsBuilder: (query) {
            final q = query.text.trim().toLowerCase();
            if (q.isEmpty) return suggestions.take(8);
            return suggestions
                .where((team) => team.toLowerCase().contains(q))
                .take(8);
          },
          onSelected: (value) {
            controller.text = value;
          },
          fieldViewBuilder: (context, fieldController, focusNode, onSubmit) {
            fieldController.text = controller.text;
            fieldController.selection = TextSelection.fromPosition(
              TextPosition(offset: fieldController.text.length),
            );
            fieldController.addListener(() {
              if (fieldController.text != controller.text) {
                controller.text = fieldController.text;
              }
            });
            controller.addListener(() {
              if (controller.text != fieldController.text) {
                fieldController.text = controller.text;
              }
            });

            return TextField(
              controller: fieldController,
              focusNode: focusNode,
              textAlign: TextAlign.right,
              textDirection: TextDirection.rtl,
              decoration: InputDecoration(
                hintText: hint ?? 'הקלד שם נבחרת',
                hintTextDirection: TextDirection.rtl,
                filled: true,
                fillColor: theme.colorScheme.surfaceContainerHighest,
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(12),
                  borderSide: BorderSide.none,
                ),
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: 16,
                  vertical: 16,
                ),
              ),
            );
          },
        ),
      ],
    );
  }
}
