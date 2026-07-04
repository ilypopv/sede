$ErrorActionPreference = "Stop"

$installRoot = Join-Path $env:LOCALAPPDATA "sede"
$configDir = Join-Path $env:APPDATA "sede"

if (Test-Path $installRoot) {
    Remove-Item -Recurse -Force $installRoot
}

if (Test-Path $configDir) {
    Remove-Item -Recurse -Force $configDir
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath) {
    $parts = $userPath -split ';' | Where-Object { $_ -and ($_ -ne (Join-Path $installRoot "bin")) }
    [Environment]::SetEnvironmentVariable("Path", ($parts -join ';'), "User")
}

Write-Host "sede has been removed from this user profile."
Write-Host "Note: assistant session data in ~/.claude and ~/.copilot was not modified."
