<#
.SYNOPSIS
    ULTIMATE AIS DATA DOWNLOADER (v14.0 - NO HARD TIMEOUT + STALL WATCHDOG)
    1. TIMEOUT: NO HARD CAP (infinite request timeout; cancels only if the download stalls).
    2. RESUME: Appends to partial files. Does NOT restart from 0 on timeout.
    3. LOGIC: Downloads first, extracts later (Phase 3) for maximum speed.
#>

[CmdletBinding()]
param()

# --- 1. SETUP ---
try {
    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
} catch {}

# Optimization settings
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
[System.Net.ServicePointManager]::DefaultConnectionLimit = 50

# --- 2. CONFIGURATION ---
$BaseDestination = "C:\Users\Jack0\GitHub\global_supply_chain_inflation_analysis\data\raw\marinecadastre_vesseltraffic_2022_2024"
$UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"

# Threads: 5 Concurrent Downloads
$MaxConcurrentDownloads = 5 
# Retries: High retry count because we expect timeouts on slow connections
$MaxRetries = 20

# Download timeout behavior:
# - Overall request timeout: infinite (prevents the 5-minute cap from killing large downloads)
# - Header timeout: cancels if the server doesn't return headers quickly (stuck TCP/SSL)
# - Stall timeout: cancels if no bytes are received for N seconds while streaming
$OverallRequestTimeout = [System.Threading.Timeout]::InfiniteTimeSpan
$HeaderTimeoutSec = 45
$ReadStallTimeoutSec = 90

# --- 3. INPUT ---
$InputYear = Read-Host "Enter Year (2022, 2023, 2024, 2025)"
if ($InputYear -notin '2022','2023','2024','2025') { Write-Error "Invalid Year"; exit }
$Year = [int]$InputYear

$DestPath = Join-Path $BaseDestination $Year
if (-not (Test-Path $DestPath)) { New-Item -ItemType Directory -Force -Path $DestPath | Out-Null }

Write-Host "`n------------------------------------------------"
Write-Host "PHASE 1: GENERATING FILE LIST" -ForegroundColor Cyan
Write-Host "------------------------------------------------"

# We use the Blind Generator to ensure 100% coverage
$FoundLinks = @()
$StartDate = Get-Date -Year $Year -Month 1 -Day 1
$EndDate = Get-Date -Year $Year -Month 12 -Day 31
if ($Year -eq (Get-Date).Year) { $EndDate = (Get-Date).AddDays(-1) }

$Current = $StartDate
while ($Current -le $EndDate) {
    $DateStr = $Current.ToString("MM_dd")
    $FName = "AIS_${Year}_${DateStr}.zip"
    $FoundLinks += [PSCustomObject]@{
        FileName = $FName
        Url = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/$Year/$FName"
    }
    $Current = $Current.AddDays(1)
}

# Filter out already extracted CSVs
$Queue = [System.Collections.Concurrent.ConcurrentQueue[PSCustomObject]]::new()
foreach ($Item in $FoundLinks) {
    $CsvName = $Item.FileName.Replace(".zip", ".csv")
    if (-not (Test-Path (Join-Path $DestPath $CsvName))) {
         $Queue.Enqueue($Item)
    }
}

$TotalFiles = $Queue.Count
Write-Host "Queued $TotalFiles files." -ForegroundColor Green

# --- 4. WORKER DEFINITION (NO HARD TIMEOUT + RESUME + STALL WATCHDOG) ---
$WorkerBlock = {
    param($Queue, $DestPath, $UserAgent, $MaxRetries, $OverallRequestTimeout, $HeaderTimeoutSec, $ReadStallTimeoutSec)
    
    Add-Type -AssemblyName System.Net.Http
    
    $Handler = [System.Net.Http.HttpClientHandler]::new()
    # Decompression is harmless for ZIPs and helps if the server ever serves compressed CSVs/metadata.
    $Handler.AutomaticDecompression = [System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate

    $Client = [System.Net.Http.HttpClient]::new($Handler)

    # Remove the 5-minute cap: set an infinite request timeout. (We still cancel stuck downloads via header/stall watchdogs.)
    $Client.Timeout = $OverallRequestTimeout
    $Client.DefaultRequestHeaders.Add("User-Agent", $UserAgent)
    $Client.DefaultRequestHeaders.Connection.Add("keep-alive")

    $Item = $null
    while ($Queue.TryDequeue([ref]$Item)) {
        
        $LocalZipPath = Join-Path $DestPath $Item.FileName
        $Success = $false
        $RetryCount = 0

        while (-not $Success -and $RetryCount -lt $MaxRetries) {
            try {
                # Check for existing partial file
                $ExistingLength = 0
                if (Test-Path $LocalZipPath) {
                    $ExistingLength = (Get-Item $LocalZipPath).Length
                }

                # Setup Request
                $Request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $Item.Url)
                
                # Append Mode (Resume) vs Create Mode
                if ($ExistingLength -gt 0) {
                    $Request.Headers.Range = [System.Net.Http.Headers.RangeHeaderValue]::new($ExistingLength, $null)
                    $FileMode = [System.IO.FileMode]::Append
                } else {
                    $FileMode = [System.IO.FileMode]::Create
                }

                # Send Request
                $HeaderCts = [System.Threading.CancellationTokenSource]::new()
                $HeaderCts.CancelAfter([TimeSpan]::FromSeconds($HeaderTimeoutSec))
                $Response = $Client.SendAsync($Request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead, $HeaderCts.Token).GetAwaiter().GetResult()
                $HeaderCts.Dispose()

                # If we requested a Range but got 200 OK, the server ignored Range.
                # Appending would corrupt the file, so restart from 0.
                if ($ExistingLength -gt 0 -and $Response.StatusCode -eq [System.Net.HttpStatusCode]::OK) {
                    try { $Response.Dispose() } catch {}
                    Remove-Item -Force $LocalZipPath -ErrorAction SilentlyContinue
                    $ExistingLength = 0
                    $Request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $Item.Url)
                    $FileMode = [System.IO.FileMode]::Create
                    $HeaderCts = [System.Threading.CancellationTokenSource]::new()
                    $HeaderCts.CancelAfter([TimeSpan]::FromSeconds($HeaderTimeoutSec))
                    $Response = $Client.SendAsync($Request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead, $HeaderCts.Token).GetAwaiter().GetResult()
                    $HeaderCts.Dispose()
                }

                # Handle Range Not Satisfiable (416) -> File is finished
                if ($Response.StatusCode -eq [System.Net.HttpStatusCode]::RequestedRangeNotSatisfiable) {
                    $Success = $true
                    break
                }
                
                # Handle Not Found (404) -> Try CSV
                if ($Response.StatusCode -eq [System.Net.HttpStatusCode]::NotFound -and $Item.FileName.EndsWith(".zip")) {
                    $CsvUrl = $Item.Url.Replace(".zip", ".csv")
                    $NewReq = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $CsvUrl)
                    $HeaderCts = [System.Threading.CancellationTokenSource]::new()
                    $HeaderCts.CancelAfter([TimeSpan]::FromSeconds($HeaderTimeoutSec))
                    $Response = $Client.SendAsync($NewReq, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead, $HeaderCts.Token).GetAwaiter().GetResult()
                    $HeaderCts.Dispose()
                    if ($Response.IsSuccessStatusCode) {
                        $Item.FileName = $Item.FileName.Replace(".zip", ".csv")
                        $LocalZipPath = $LocalZipPath.Replace(".zip", ".csv")
                        $FileMode = [System.IO.FileMode]::Create
                    }
                }

                if (-not $Response.IsSuccessStatusCode) { throw "HTTP $($Response.StatusCode)" }

                # Stream Copy
                $NetworkStream = $Response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                $FileStream = [System.IO.FileStream]::new($LocalZipPath, $FileMode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
                
                $Buffer = New-Object byte[] 1048576  # 1 MiB buffer reduces overhead on high-bandwidth links
                $BytesRead = 0
                do {
                    $ReadCts = [System.Threading.CancellationTokenSource]::new()
                    $ReadCts.CancelAfter([TimeSpan]::FromSeconds($ReadStallTimeoutSec))

                    $BytesRead = $NetworkStream.ReadAsync($Buffer, 0, $Buffer.Length, $ReadCts.Token).GetAwaiter().GetResult()
                    $ReadCts.Dispose()

                    if ($BytesRead -gt 0) {
                        $FileStream.Write($Buffer, 0, $BytesRead)
                    }
                } while ($BytesRead -gt 0)
                $FileStream.Close()
                $NetworkStream.Close()
                try { $Response.Dispose() } catch {}
                $Success = $true
            }
            catch {
                # ON ERROR / TIMEOUT
                $RetryCount++
                $Msg = "Error on $($Item.FileName): $($_.Exception.Message)"
                Add-Content (Join-Path $DestPath "download_errors.log") $Msg
                
                # DO NOT DELETE FILE. Just wait and retry to resume.
                Start-Sleep -Seconds 2
            }
        }
    }
    $Client.Dispose()
}

# --- 5. EXECUTION ---
Write-Host "------------------------------------------------"
Write-Host "PHASE 2: DOWNLOADING (NO HARD TIMEOUT; STALL WATCHDOG)" -ForegroundColor Cyan
Write-Host "------------------------------------------------"

$RunspacePool = [runspacefactory]::CreateRunspacePool(1, $MaxConcurrentDownloads)
$RunspacePool.Open()
$Jobs = @()

for ($i=0; $i -lt $MaxConcurrentDownloads; $i++) {
    $PS = [powershell]::Create()
    $PS.RunspacePool = $RunspacePool
    [void]$PS.AddScript($WorkerBlock)
    [void]$PS.AddArgument($Queue)
    [void]$PS.AddArgument($DestPath)
    [void]$PS.AddArgument($UserAgent)
    [void]$PS.AddArgument($MaxRetries)
    [void]$PS.AddArgument($OverallRequestTimeout)
    [void]$PS.AddArgument($HeaderTimeoutSec)
    [void]$PS.AddArgument($ReadStallTimeoutSec)
    $Jobs += [PSCustomObject]@{ PS=$PS; Result=$PS.BeginInvoke() }
}

# Monitor
while ($Queue.Count -gt 0) {
    $Rem = $Queue.Count
    $Done = $TotalFiles - $Rem
    $Pct = 0; if ($TotalFiles -gt 0) { $Pct = ($Done / $TotalFiles) * 100 }
    Write-Progress -Activity "Downloading..." -Status "$Rem remaining ($Done done)" -PercentComplete $Pct
    Start-Sleep -Seconds 5
}

foreach ($j in $Jobs) { try { $j.PS.EndInvoke($j.Result) } catch {}; $j.PS.Dispose() }
$RunspacePool.Close()

Write-Host "Downloads Complete." -ForegroundColor Green

# --- 6. EXTRACTION ---
Write-Host "------------------------------------------------"
Write-Host "PHASE 3: EXTRACTION" -ForegroundColor Cyan
Write-Host "------------------------------------------------"

Add-Type -AssemblyName System.IO.Compression.FileSystem
$Zips = Get-ChildItem -Path $DestPath -Filter "*.zip"
$TotalZips = $Zips.Count
$Count = 0

foreach ($Zip in $Zips) {
    $Count++
    Write-Progress -Activity "Extracting..." -Status "$($Zip.Name)" -PercentComplete (($Count / $TotalZips) * 100)
    try {
        [System.IO.Compression.ZipFile]::ExtractToDirectory($Zip.FullName, $DestPath)
        Remove-Item $Zip.FullName -Force
    } catch {
        Write-Warning "Extract Failed: $($Zip.Name)"
    }
}

Write-Host "DONE." -ForegroundColor Green