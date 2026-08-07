<#
.SYNOPSIS
  NOAA Marine Cadastre AIS Downloader (FIXED for 3-year batches + 2025 naming)
.DESCRIPTION
  Key features:
  1) Parse NOAA index.html per year for exact filenames
  2) Fast concurrent downloads with resume capability
  3) Optional ZIP extraction
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$false)]
  [ValidateSet("2009-2011", "2012-2014", "2015-2017", "2018-2020", "2021-2023", "2024-2025", "CUSTOM", "SINGLE", "2019", "2020", "2021")]
  [string]$BatchMode = "SINGLE",

  [Parameter(Mandatory=$false)]
  [int[]]$CustomYears,

  [Parameter(Mandatory=$false)]
  [int]$MaxParallel = 5,

  [Parameter(Mandatory=$false)]
  [bool]$ExtractZips = $true,

  [Parameter(Mandatory=$false)]
  [int]$HeaderTimeoutSeconds = 45,

  [Parameter(Mandatory=$false)]
  [int]$ReadStallTimeoutSeconds = 120,

  [Parameter(Mandatory=$false)]
  [int]$MaxRetries = 20,

  [Parameter(Mandatory=$false)]
  [string]$StartFromDate = "",

  [Parameter(Mandatory=$false)]
  [switch]$SkipExisting = $false
)

$BaseUrl = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DefaultDestination = Join-Path $ScriptDir "marinecadastre_ais_historical"

$Batches = @{
  "2009-2011" = @(2009, 2010, 2011)
  "2012-2014" = @(2012, 2013, 2014)
  "2015-2017" = @(2015, 2016, 2017)
  "2018-2020" = @(2018, 2019, 2020)
  "2021-2023" = @(2021, 2022, 2023)
  "2024-2025" = @(2024, 2025)
  "2019" = @(2019)
  "2020" = @(2020)
  "2021" = @(2021)
}

$UserAgent = "HyperQuant-AIS-Downloader/1.0"
$OverallRequestTimeout = [System.Threading.Timeout]::InfiniteTimeSpan

try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch {}
try { Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue } catch {}
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
[System.Net.ServicePointManager]::DefaultConnectionLimit = 50

function Get-YearsToDownload {
  param([string]$Mode, [int[]]$Custom)
  switch ($Mode) {
    "CUSTOM" {
      if (-not $Custom -or $Custom.Count -eq 0) { throw "CustomYears required" }
      return $Custom
    }
    "SINGLE" {
      Write-Host "Enter year (2009-2025):" -ForegroundColor Cyan
      $year = Read-Host
      $y = [int]$year
      return @($y)
    }
    default {
      return $Batches[$Mode]
    }
  }
}

function Get-FileListForYear {
  param([int]$Year)
  $indexUrl = "$BaseUrl/$Year/index.html"
  Write-Host "Fetching $Year..." -ForegroundColor DarkCyan
  
  $resp = Invoke-WebRequest -Uri $indexUrl -UseBasicParsing -ErrorAction Stop
  $hrefs = [regex]::Matches($resp.Content, 'href="([^"]+)"') | ForEach-Object { $_.Groups[1].Value }
  $files = $hrefs | Where-Object { $_ -match '\.zip$' -or $_ -match '\.csv\.zst$' }
  
  if (-not $files -or $files.Count -eq 0) {
    throw "No files found for $Year"
  }
  
  return $files | ForEach-Object {
    [PSCustomObject]@{
      Year     = $Year
      FileName = $_
      Url      = "$BaseUrl/$Year/$_"
      IsZip    = ($_ -like "*.zip")
      IsZst    = ($_ -like "*.csv.zst")
    }
  }
}

function Test-AlreadyHave {
  param([PSCustomObject]$Item, [string]$YearDir)
  
  if ($Item.IsZip) {
    $marker = Join-Path $YearDir (($Item.FileName -replace '\.zip$', '') + ".extracted.ok")
    if (Test-Path $marker) { return $true }
  }
  
  $local = Join-Path $YearDir $Item.FileName
  if (-not (Test-Path $local)) { return $false }
  
  $localSize = (Get-Item $local).Length
  return ($localSize -gt 1000)
}

$WorkerBlock = {
  param($Queue, $UserAgent, $OverallRequestTimeout, $HeaderTimeoutSeconds, $ReadStallTimeoutSeconds, $MaxRetries)
  
  Add-Type -AssemblyName System.Net.Http
  
  $Handler = [System.Net.Http.HttpClientHandler]::new()
  $Handler.AutomaticDecompression = [System.Net.DecompressionMethods]::GZip -bor [System.Net.DecompressionMethods]::Deflate
  $Client = [System.Net.Http.HttpClient]::new($Handler)
  $Client.Timeout = $OverallRequestTimeout
  $Client.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", $UserAgent) | Out-Null
  
  $item = $null
  while ($Queue.TryDequeue([ref]$item)) {
    $dest = $item.LocalPath
    $destDir = Split-Path -Parent $dest
    if (-not (Test-Path $destDir)) { New-Item -ItemType Directory -Force -Path $destDir | Out-Null }
    
    $ok = $false
    $attempt = 0
    
    while (-not $ok -and $attempt -lt $MaxRetries) {
      $attempt++
      $resp = $null
      $fs = $null
      $ns = $null
      
      try {
        $existing = 0
        if (Test-Path $dest) { $existing = (Get-Item $dest).Length }
        
        $req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $item.Url)
        $fileMode = [System.IO.FileMode]::Create
        
        if ($existing -gt 0) {
          $req.Headers.Range = [System.Net.Http.Headers.RangeHeaderValue]::new($existing, $null)
          $fileMode = [System.IO.FileMode]::Append
        }
        
        $hcts = [System.Threading.CancellationTokenSource]::new()
        $hcts.CancelAfter([TimeSpan]::FromSeconds($HeaderTimeoutSeconds))
        $resp = $Client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead, $hcts.Token).GetAwaiter().GetResult()
        $hcts.Dispose()
        
        if ($existing -gt 0 -and $resp.StatusCode -eq [System.Net.HttpStatusCode]::OK) {
          try { $resp.Dispose() } catch {}
          Remove-Item -Force $dest -ErrorAction SilentlyContinue
          $existing = 0
          $req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $item.Url)
          $fileMode = [System.IO.FileMode]::Create
          $hcts = [System.Threading.CancellationTokenSource]::new()
          $hcts.CancelAfter([TimeSpan]::FromSeconds($HeaderTimeoutSeconds))
          $resp = $Client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead, $hcts.Token).GetAwaiter().GetResult()
          $hcts.Dispose()
        }
        
        if ($resp.StatusCode -eq [System.Net.HttpStatusCode]::RequestedRangeNotSatisfiable) {
          $ok = $true
          break
        }
        
        if (-not $resp.IsSuccessStatusCode) {
          if ($resp.StatusCode -eq [System.Net.HttpStatusCode]::NotFound) {
            throw "HTTP 404"
          }
          throw ("HTTP " + $resp.StatusCode)
        }
        
        $ns = $resp.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $fs = [System.IO.FileStream]::new($dest, $fileMode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        
        $buf = New-Object byte[] 1048576
        while ($true) {
          $rcts = [System.Threading.CancellationTokenSource]::new()
          $rcts.CancelAfter([TimeSpan]::FromSeconds($ReadStallTimeoutSeconds))
          $n = $ns.ReadAsync($buf, 0, $buf.Length, $rcts.Token).GetAwaiter().GetResult()
          $rcts.Dispose()
          
          if ($n -le 0) { break }
          $fs.Write($buf, 0, $n)
        }
        
        $ok = $true
      }
      catch {
        Start-Sleep -Seconds 2
      }
      finally {
        try { if ($fs) { $fs.Dispose() } } catch {}
        try { if ($ns) { $ns.Dispose() } } catch {}
        try { if ($resp) { $resp.Dispose() } } catch {}
      }
    }
  }
  
  $Client.Dispose()
}

Write-Host ""
Write-Host "AIS Data Downloader" -ForegroundColor Cyan
Write-Host ""

$yearsToDownload = Get-YearsToDownload -Mode $BatchMode -Custom $CustomYears
$yearsToDownload = $yearsToDownload | Sort-Object -Unique

$batchName = if ($yearsToDownload.Count -eq 1) { $yearsToDownload[0].ToString() } else { ($yearsToDownload[0].ToString() + "-" + $yearsToDownload[-1].ToString()) }

$destination = Join-Path $DefaultDestination ("batch_" + $batchName)
Write-Host "Destination: $destination" -ForegroundColor Green
if (-not (Test-Path $destination)) { New-Item -ItemType Directory -Force -Path $destination | Out-Null }

$allFiles = @()
foreach ($yr in $yearsToDownload) {
  try {
    $files = Get-FileListForYear -Year $yr
    
    # Apply date filter if specified
    if ($StartFromDate) {
      $startDate = [DateTime]::ParseExact($StartFromDate, "yyyy-MM-dd", $null)
      $files = $files | Where-Object {
        $fileName = $_.FileName
        # Extract date from filename (e.g., AIS_2018_01_15.zip)
        if ($fileName -match '(\d{4})_(\d{2})_(\d{2})') {
          $fileDate = [DateTime]::new([int]$matches[1], [int]$matches[2], [int]$matches[3])
          return $fileDate -ge $startDate
        }
        return $true
      }
    }
    
    $allFiles += $files
  }
  catch {
    Write-Warning "Failed to get files for $yr : $_"
  }
}

Write-Host ("Found " + $allFiles.Count + " files to download") -ForegroundColor Green

$queue = [System.Collections.Concurrent.ConcurrentQueue[PSCustomObject]]::new()

foreach ($item in $allFiles) {
  $yearDir = Join-Path $destination $item.Year.ToString()
  
  # Skip files that are already processed (if SkipExisting flag set)
  if ($SkipExisting) {
    $processedMarker = Join-Path $yearDir (($item.FileName -replace '\.(zip|csv\.zst)$', '') + ".processed.ok")
    if (Test-Path $processedMarker) {
      continue
    }
  }
  
  if (-not (Test-AlreadyHave -Item $item -YearDir $yearDir)) {
    $item | Add-Member -NotePropertyName LocalPath -NotePropertyValue (Join-Path $yearDir $item.FileName) -Force
    $queue.Enqueue($item)
  }
}

Write-Host ("Queued " + $queue.Count + " files for download") -ForegroundColor Green

if ($queue.Count -eq 0) {
  Write-Host "All files already present."
}
else {
  $pool = [runspacefactory]::CreateRunspacePool(1, $MaxParallel)
  $pool.Open()
  
  $jobs = @()
  for ($i = 0; $i -lt $MaxParallel; $i++) {
    $ps = [powershell]::Create()
    $ps.RunspacePool = $pool
    $null = $ps.AddScript($WorkerBlock)
    $null = $ps.AddArgument($queue)
    $null = $ps.AddArgument($UserAgent)
    $null = $ps.AddArgument($OverallRequestTimeout)
    $null = $ps.AddArgument($HeaderTimeoutSeconds)
    $null = $ps.AddArgument($ReadStallTimeoutSeconds)
    $null = $ps.AddArgument($MaxRetries)
    
    $handle = $ps.BeginInvoke()
    $jobs += @{PS = $ps; Handle = $handle}
  }
  
  while ($queue.Count -gt 0) {
    Write-Host ("Downloading... " + $queue.Count + " remaining") -ForegroundColor Yellow
    Start-Sleep -Seconds 5
  }
  
  foreach ($j in $jobs) { try { $j.PS.EndInvoke($j.Handle) } catch {}; $j.PS.Dispose() }
  $pool.Close()
  
  Write-Host "Downloads complete." -ForegroundColor Green
}

if ($ExtractZips) {
  Write-Host ""
  Write-Host "Extracting ZIPs..." -ForegroundColor Cyan
  $zips = Get-ChildItem -Path $destination -Filter "*.zip" -Recurse -ErrorAction SilentlyContinue
  if ($zips -and $zips.Count -gt 0) {
    $count = 0
    foreach ($z in $zips) {
      $count++
      Write-Progress -Activity "Extracting" -Status $z.Name -PercentComplete (($count / $zips.Count) * 100)
      try {
        [System.IO.Compression.ZipFile]::ExtractToDirectory($z.FullName, $z.DirectoryName)
        Remove-Item -Force $z.FullName
        $marker = Join-Path $z.DirectoryName (($z.BaseName) + ".extracted.ok")
        Set-Content -Path $marker -Value "ok" -Encoding ascii
      }
      catch {
        Write-Warning ("Failed: " + $z.Name)
      }
    }
    Write-Host "Done." -ForegroundColor Green
  }
}

Write-Host "Completed." -ForegroundColor Green
