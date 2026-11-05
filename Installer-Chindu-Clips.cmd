@echo off
setlocal
title Chindu Clips - Installation du moteur
set "CHINDU_INSTALLER=%~f0"
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; $raw=Get-Content -LiteralPath $env:CHINDU_INSTALLER -Raw; & ([scriptblock]::Create(($raw -split '(?m)^# POWERSHELL_START\r?$',2)[1]))"
if errorlevel 1 (
  echo.
  echo Installation non terminee. Consultez le message ci-dessus.
)
echo.
pause
exit /b
# POWERSHELL_START
$ErrorActionPreference = 'Stop'
try {
    Write-Host 'CHINDU CLIPS - Installation personnelle' -ForegroundColor Cyan
    Write-Host 'Ce lanceur installe le moteur dans votre dossier utilisateur.'
    Write-Host ''
    $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
    $dockerPath = if ($docker) { $docker.Source } else { Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe' }
    if (-not (Test-Path -LiteralPath $dockerPath)) {
        Write-Host 'Docker Desktop doit etre installe avant de continuer.' -ForegroundColor Yellow
        Write-Host 'Installez Docker Desktop, ouvrez-le, puis relancez ce fichier.'
        Start-Process 'https://docs.docker.com/desktop/setup/install/windows-install/'
        exit 1
    }
    & $dockerPath info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Docker est installe mais ne repond pas.' -ForegroundColor Yellow
        Write-Host 'Ouvrez Docker Desktop et attendez son demarrage, puis relancez ce fichier.'
        exit 1
    }
    & $dockerPath compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose est absent. Mettez Docker Desktop a jour.' }
    $osType = & $dockerPath info --format '{{.OSType}}'
    if ($osType.Trim() -ne 'linux') { throw 'Activez les conteneurs Linux dans Docker Desktop puis relancez.' }
    $root = Join-Path $env:LOCALAPPDATA 'ChinduClips'
    $engine = Join-Path $root 'chindu-clips-engine'
    New-Item -ItemType Directory -Path $root -Force | Out-Null
    if (-not (Test-Path -LiteralPath (Join-Path $engine 'compose.yaml'))) {
        $zip = Join-Path $root 'engine.zip'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Write-Host 'Telechargement du moteur depuis votre depot GitHub...'
        Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/Bifrii/Chinduclips/a087bd4a9d0ebd30337c1dba0488cdbcc1c91285/dist/chindu-clips-engine.zip' -OutFile $zip
        if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne '1730eddea809521b6778b79284499951983f57074a92a4a21d50b1a8cc7f3419') {
            Remove-Item -LiteralPath $zip -Force
            throw 'Le fichier telecharge ne correspond pas au moteur attendu.'
        }
        Expand-Archive -LiteralPath $zip -DestinationPath $root -Force
        Remove-Item -LiteralPath $zip -Force
    }
    # Update engine code only. Preserve .env, video/model volumes and web assets.
    Write-Host 'Mise a jour du moteur YouTube...'
    $updateFiles = @('Dockerfile', 'requirements.txt', 'server.py', 'web/app.js', 'web/style.css')
    foreach ($name in $updateFiles) {
        $target = Join-Path $engine ($name + '.next')
        Invoke-WebRequest -UseBasicParsing -Uri ("https://raw.githubusercontent.com/Bifrii/Chinduclips/01d9ececbaa02054a35ce49e34b8dce286c9759e/engine/" + $name) -OutFile $target
    }
    foreach ($name in $updateFiles) {
        Move-Item -LiteralPath (Join-Path $engine ($name + '.next')) -Destination (Join-Path $engine $name) -Force
    }
    $envFile = Join-Path $engine '.env'
    if (-not (Test-Path -LiteralPath $envFile)) {
        $bytes = New-Object byte[] 32
        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
        $key = -join ($bytes | ForEach-Object { $_.ToString('x2') })
        [IO.File]::WriteAllText($envFile, "CLIP_API_KEY=$key" + [Environment]::NewLine, [Text.Encoding]::ASCII)
    }
    Push-Location $engine
    try {
        Write-Host 'Construction et lancement. Le premier demarrage peut prendre plusieurs minutes.'
        & $dockerPath compose -p chinduclips up -d --build
        if ($LASTEXITCODE -ne 0) { throw 'Docker ne peut pas demarrer le moteur. Consultez les messages ci-dessus.' }
        # Repair existing model volumes created before the cache ownership fix.
        & $dockerPath compose -p chinduclips exec -T --user root clips chown -R clip:clip /home/clip/.cache
        if ($LASTEXITCODE -ne 0) { throw 'Impossible de corriger les droits du cache Whisper.' }
        & $dockerPath compose -p chinduclips restart clips
        if ($LASTEXITCODE -ne 0) { throw 'Impossible de redemarrer le moteur.' }
    } finally { Pop-Location }
    $keyLine = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^CLIP_API_KEY=' } | Select-Object -First 1
    if (-not $keyLine) { throw 'La cle CLIP_API_KEY est absente du fichier .env.' }
    $apiKey = $keyLine.Substring(13)
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://localhost:8080/api/health' -Headers @{Authorization="Bearer $apiKey"} -TimeoutSec 3
            if ($health.ok) { $ready = $true; break }
        } catch { Start-Sleep -Seconds 2 }
    }
    if (-not $ready) { throw 'Le moteur ne repond pas encore. Dans le dossier moteur, executez : docker compose -p chinduclips logs --tail 50' }
    Write-Host ''
    Write-Host 'Le moteur est demarre !' -ForegroundColor Green
    Write-Host 'Dans le studio, cliquez Connecter le moteur.'
    Write-Host 'Adresse : http://localhost:8080'
    Write-Host 'Le Bloc-notes va ouvrir votre fichier .env.'
    Write-Host 'Copiez uniquement la valeur apres CLIP_API_KEY= dans le champ Cle privee.'
    Write-Host 'Gardez cette cle sur votre ordinateur.'
    Write-Host "Dossier moteur : $engine"
    Start-Process notepad.exe -ArgumentList ('"' + $envFile + '"')
    Start-Process 'http://localhost:8080'
} catch {
    Write-Host ''
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
