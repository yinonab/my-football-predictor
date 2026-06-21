import 'package:flutter/material.dart';

/// Team picker with autocomplete. Clears on focus, closes overlay on selection.
class TeamTextField extends StatefulWidget {
  final String label;
  final TextEditingController controller;
  final FocusNode focusNode;
  final VoidCallback? onFocusGained;
  final String? hint;
  final List<String> suggestions;
  final String? groupBadge;

  const TeamTextField({
    super.key,
    required this.label,
    required this.controller,
    required this.focusNode,
    this.onFocusGained,
    this.hint,
    this.suggestions = const [],
    this.groupBadge,
  });

  @override
  State<TeamTextField> createState() => _TeamTextFieldState();
}

class _TeamTextFieldState extends State<TeamTextField> {
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            if (widget.groupBadge != null)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: theme.colorScheme.secondaryContainer,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  'בית ${widget.groupBadge}',
                  style: theme.textTheme.labelMedium,
                ),
              )
            else
              const SizedBox.shrink(),
            Text(
              widget.label,
              style: theme.textTheme.titleSmall?.copyWith(
                fontWeight: FontWeight.w600,
              ),
              textAlign: TextAlign.right,
            ),
          ],
        ),
        const SizedBox(height: 8),
        RawAutocomplete<String>(
          textEditingController: widget.controller,
          focusNode: widget.focusNode,
          optionsBuilder: (TextEditingValue value) {
            final q = value.text.trim().toLowerCase();
            if (q.isEmpty) return widget.suggestions.take(8);
            return widget.suggestions
                .where((team) => team.toLowerCase().contains(q))
                .take(8);
          },
          onSelected: (String selection) {
            widget.controller.text = selection;
            widget.controller.selection = TextSelection.collapsed(
              offset: selection.length,
            );
            widget.focusNode.unfocus();
          },
          fieldViewBuilder: (context, controller, focusNode, onSubmitted) {
            return TextField(
              controller: controller,
              focusNode: focusNode,
              textAlign: TextAlign.right,
              textDirection: TextDirection.rtl,
              onTap: () {
                widget.onFocusGained?.call();
                if (controller.text.isNotEmpty) {
                  controller.clear();
                }
              },
              decoration: InputDecoration(
                hintText: widget.hint ?? 'הקלד שם נבחרת',
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
          optionsViewBuilder: (context, onSelected, options) {
            if (options.isEmpty) return const SizedBox.shrink();

            return Align(
              alignment: AlignmentDirectional.topStart,
              child: Material(
                elevation: 4,
                borderRadius: BorderRadius.circular(12),
                clipBehavior: Clip.antiAlias,
                child: ConstrainedBox(
                  constraints: BoxConstraints(
                    maxHeight: 220,
                    maxWidth: MediaQuery.sizeOf(context).width - 32,
                  ),
                  child: ListView.builder(
                    padding: EdgeInsets.zero,
                    shrinkWrap: true,
                    itemCount: options.length,
                    itemBuilder: (context, index) {
                      final option = options.elementAt(index);
                      return ListTile(
                        dense: true,
                        title: Text(
                          option,
                          textAlign: TextAlign.right,
                          textDirection: TextDirection.rtl,
                        ),
                        onTap: () => onSelected(option),
                      );
                    },
                  ),
                ),
              ),
            );
          },
        ),
      ],
    );
  }
}
