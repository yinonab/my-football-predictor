# Clean release APK build; restores tracked mobile/build/web for Render (see .cursor/rules/mobile-apk-clean-build.mdc)
$ErrorActionPreference = "Stop"

$MobileDir = Split-Path $PSScriptRoot -Parent
$RepoRoot = Split-Path $MobileDir -Parent
$ApkPath = Join-Path $MobileDir "build\app\outputs\flutter-apk\app-release.apk"

Push-Location $MobileDir
try {
    flutter clean
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    flutter pub get
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    flutter build apk --release
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Push-Location $RepoRoot
try {
    git restore mobile/build/web
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "APK ready: $ApkPath"
