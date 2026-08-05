<#!
.SYNOPSIS
Resumes the staged national AIS Zenodo draft and verifies every uploaded file.

.DESCRIPTION
Uses ZENODO_API_TOKEN from the repository .env file. It never submits or
publishes the draft, and refuses to replace a remote file whose checksum does
not match the staged release.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$stage = Join-Path $env:TEMP "national_ais_release_21653033"
$envPath = Join-Path $repo ".env"
$depositUrl = "https://zenodo.org/api/deposit/depositions/21653033"

if (-not (Test-Path -LiteralPath $stage)) { throw "Staging directory missing: $stage" }
$line = Get-Content -LiteralPath $envPath | Where-Object { $_ -match '^\s*ZENODO_API_TOKEN\s*=' } | Select-Object -First 1
if (-not $line) { throw "ZENODO_API_TOKEN missing from .env" }
$token = (($line -split "=", 2)[1].Trim().Trim('"').Trim("'"))
if ([string]::IsNullOrWhiteSpace($token)) { throw "ZENODO_API_TOKEN is empty" }
$headers = @{ Authorization = "Bearer $token" }

function Get-Draft {
    Invoke-RestMethod -Uri $depositUrl -Headers $headers -Method Get -TimeoutSec 60
}

function Get-RemoteMap($draft) {
    $map = @{}
    foreach ($remote in @($draft.files)) { $map[$remote.filename] = $remote }
    $map
}

function Get-Md5($path) {
    $stream = [System.IO.File]::OpenRead($path)
    try {
        ([System.BitConverter]::ToString([System.Security.Cryptography.MD5]::Create().ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
    } finally {
        $stream.Dispose()
    }
}

$draft = Get-Draft
if ($draft.submitted) { throw "Draft is already submitted; refusing to alter it." }
$bucket = $draft.links.bucket
$remote = Get-RemoteMap $draft
$files = @(Get-ChildItem -LiteralPath $stage -File | Sort-Object Length, Name)

foreach ($file in $files) {
    $localMd5 = Get-Md5 $file.FullName
    if ($remote.ContainsKey($file.Name)) {
        $remoteMd5 = ([string]$remote[$file.Name].checksum).ToLowerInvariant() -replace '^md5:', ''
        if (($remote[$file.Name].filesize -eq $file.Length) -and ($remoteMd5 -eq $localMd5)) {
            Write-Output "SKIP $($file.Name) checksum verified"
            continue
        }
        throw "Remote file differs from staged file: $($file.Name); refusing replacement."
    }

    Write-Output "UPLOAD $($file.Name) bytes=$($file.Length)"
    $target = "$bucket/$([uri]::EscapeDataString($file.Name))"
    Invoke-RestMethod -Uri $target -Headers $headers -Method Put -InFile $file.FullName -ContentType "application/octet-stream" -TimeoutSec 7200 | Out-Null

    $draft = Get-Draft
    $remote = Get-RemoteMap $draft
    if (-not $remote.ContainsKey($file.Name)) { throw "Zenodo did not register uploaded file: $($file.Name)" }
    $remoteMd5 = ([string]$remote[$file.Name].checksum).ToLowerInvariant() -replace '^md5:', ''
    if (($remote[$file.Name].filesize -ne $file.Length) -or ($remoteMd5 -ne $localMd5)) {
        throw "Checksum mismatch after upload: $($file.Name)"
    }
    Write-Output "VERIFIED $($file.Name)"
}

$final = Get-Draft
$finalRemote = Get-RemoteMap $final
foreach ($file in $files) {
    if (-not $finalRemote.ContainsKey($file.Name)) { throw "Missing after reconciliation: $($file.Name)" }
    $remoteMd5 = ([string]$finalRemote[$file.Name].checksum).ToLowerInvariant() -replace '^md5:', ''
    if (($finalRemote[$file.Name].filesize -ne $file.Length) -or ($remoteMd5 -ne (Get-Md5 $file.FullName))) {
        throw "Final checksum mismatch: $($file.Name)"
    }
}
Write-Output "COMPLETE verified_files=$(@($final.files).Count); draft remains unsubmitted"
