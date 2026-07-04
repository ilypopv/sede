param(
    [string]$Source = "latest"
)

$ErrorActionPreference = "Stop"

$pythonCommand = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCommand = @("py", "-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCommand = @("python")
} else {
    throw "Python 3.9+ is required but was not found."
}

$installRoot = Join-Path $env:LOCALAPPDATA "sede"
$venvDir = Join-Path $installRoot "venv"
$binDir = Join-Path $installRoot "bin"
$launcherPath = Join-Path $binDir "sede.cmd"
$repoUrl = "https://github.com/ilypopv/sede.git"

if ($Source -eq "latest") {
    $packageSpec = "git+$repoUrl@main"
} else {
    $packageSpec = "git+$repoUrl@$Source"
}

Write-Host "Installing sede ($Source)..."
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

if ($pythonCommand.Length -eq 2) {
    & $pythonCommand[0] $pythonCommand[1] -m venv $venvDir
} else {
    & $pythonCommand[0] -m venv $venvDir
}
& "$venvDir\Scripts\python.exe" -m pip install --upgrade pip | Out-Null
& "$venvDir\Scripts\pip.exe" install $packageSpec

$launcherContent = "@echo off`r`n\"%~dp0..\venv\Scripts\python.exe\" -m sede %*`r`n"
Set-Content -Path $launcherPath -Value $launcherContent -Encoding ASCII

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) {
    $userPath = ""
}

if (-not (($userPath -split ';') -contains $binDir)) {
    $newPath = ($userPath.TrimEnd(';') + ";$binDir").TrimStart(';')
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "Added $binDir to User PATH. Restart terminal to apply."
}

Write-Host "sede installed successfully."
Write-Host "Binary: $launcherPath"
