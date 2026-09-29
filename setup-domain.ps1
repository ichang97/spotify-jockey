$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Start-Process powershell.exe -ArgumentList ("-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"") -Verb RunAs
    exit
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$domain = "spotify-jockey.test"
$envFile = Join-Path $scriptDir ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -match '^APP_DOMAIN=(.+)$') {
            $domain = $matches[1].Trim().Trim('"').Trim("'")
        }
    }
}

function Ensure-Mkcert {
    if (Get-Command mkcert -ErrorAction SilentlyContinue) {
        return $true
    }
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install FiloSottile.mkcert --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        if (Get-Command mkcert -ErrorAction SilentlyContinue) {
            return $true
        }
    }
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install mkcert -y
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        if (Get-Command mkcert -ErrorAction SilentlyContinue) {
            return $true
        }
    }
    if (Get-Command scoop -ErrorAction SilentlyContinue) {
        scoop install mkcert
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        if (Get-Command mkcert -ErrorAction SilentlyContinue) {
            return $true
        }
    }

    $downloadUrl = "https://github.com/FiloSottile/mkcert/releases/download/v1.4.4/mkcert-v1.4.4-windows-amd64.exe"
    $toolsDir = Join-Path $env:LOCALAPPDATA "mkcert-bin"
    if (-not (Test-Path $toolsDir)) {
        New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
    }
    $mkcertExe = Join-Path $toolsDir "mkcert.exe"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $downloadUrl -OutFile $mkcertExe
    [System.Environment]::SetEnvironmentVariable("Path", $env:Path + ";$toolsDir", [System.EnvironmentVariableTarget]::Machine)
    $env:Path += ";$toolsDir"

    return (Get-Command mkcert -ErrorAction SilentlyContinue) -ne $null
}

$mkcertReady = Ensure-Mkcert
if (-not $mkcertReady) {
    Write-Host "Error: Unable to locate or install mkcert." -ForegroundColor Red
    exit 1
}

mkcert -install

$certsDir = Join-Path $scriptDir "nginx\certs"
if (-not (Test-Path $certsDir)) {
    New-Item -ItemType Directory -Path $certsDir -Force | Out-Null
}

$certFile = Join-Path $certsDir "fullchain.pem"
$keyFile = Join-Path $certsDir "privkey.pem"

mkcert -key-file $keyFile -cert-file $certFile $domain "localhost" "127.0.0.1"

$hostsFile = "$env:SystemRoot\System32\drivers\etc\hosts"
$hostsContent = Get-Content $hostsFile -Raw
$entry = "127.0.0.1 $domain"
if ($hostsContent -notmatch "(?m)^127\.0\.0\.1\s+$([regex]::Escape($domain))") {
    Add-Content -Path $hostsFile -Value "`n$entry"
    Write-Host "Added $entry to $hostsFile" -ForegroundColor Green
} else {
    Write-Host "$domain is already mapped in $hostsFile" -ForegroundColor Cyan
}

ipconfig /flushdns | Out-Null

Write-Host ""
Write-Host "Setup Completed Successfully!" -ForegroundColor Green
Write-Host "Domain: https://$domain" -ForegroundColor Yellow
Write-Host "Next Step: Restart docker containers using 'docker compose down' and 'docker compose up -d'" -ForegroundColor Cyan
Write-Host "Spotify Redirect URI: https://$domain/auth/spotify/callback" -ForegroundColor Magenta
