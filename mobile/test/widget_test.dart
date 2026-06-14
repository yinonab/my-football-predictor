import 'package:flutter_test/flutter_test.dart';

import 'package:football_predictor/main.dart';

void main() {
  testWidgets('App loads with Hebrew title', (WidgetTester tester) async {
    await tester.pumpWidget(const FootballPredictorApp());
    await tester.pump();

    expect(find.text('מנבא כדורגל'), findsOneWidget);
  });
}
