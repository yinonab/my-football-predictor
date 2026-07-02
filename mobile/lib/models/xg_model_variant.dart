/// User-selectable xG model variant (maps to backend `xg_model_variant`).
enum XgModelVariant {
  nr3Fcc,
  matchupRelativeV1,
}

extension XgModelVariantApi on XgModelVariant {
  String get apiValue {
    switch (this) {
      case XgModelVariant.nr3Fcc:
        return 'nr3_fcc';
      case XgModelVariant.matchupRelativeV1:
        return 'matchup_relative_v1';
    }
  }

  String get settingsLabel {
    switch (this) {
      case XgModelVariant.nr3Fcc:
        return 'NR3+FCC — יציב';
      case XgModelVariant.matchupRelativeV1:
        return 'Matchup Relative — ניסיוני';
    }
  }

  String get activeBadgeLabel {
    switch (this) {
      case XgModelVariant.nr3Fcc:
        return 'מודל פעיל: NR3+FCC';
      case XgModelVariant.matchupRelativeV1:
        return 'מודל פעיל: Matchup Relative — ניסיוני';
    }
  }

  static XgModelVariant fromApi(String? value) {
    switch (value) {
      case 'matchup_relative_v1':
        return XgModelVariant.matchupRelativeV1;
      case 'nr3_fcc':
      default:
        return XgModelVariant.nr3Fcc;
    }
  }

  static XgModelVariant fromPrefs(String? value) => fromApi(value);
}
