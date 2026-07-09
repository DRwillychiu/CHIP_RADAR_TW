# =====================================================================
# Chip Radar TW - Morning Execution Report (08:10)
# =====================================================================
# Reads yesterday's scheduler JSONL + GitHub Actions results,
# displays a summary in a Windows Form dialog.
# =====================================================================
$ErrorActionPreference = "Continue"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logsDir = Join-Path $projectRoot "logs"

# ── Load .env ──
$dotenvFile = Join-Path $projectRoot ".env"
if (Test-Path $dotenvFile) {
    Get-Content $dotenvFile -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $k, $v = $line -split "=", 2
            $k = $k.Trim(); $v = $v.Trim()
            if ($v -and -not [System.Environment]::GetEnvironmentVariable($k)) {
                Set-Item -Path "env:$k" -Value $v
            }
        }
    }
}

$logFile = if ($env:CHIP_RADAR_LOG_DIR) {
    Join-Path $env:CHIP_RADAR_LOG_DIR 'chip_radar_scheduler.log'
} elseif (Test-Path "$env:USERPROFILE\Desktop") {
    "$env:USERPROFILE\Desktop\chip_radar_scheduler.log"
} else {
    Join-Path $PSScriptRoot 'chip_radar_scheduler.log'
}

# ── Determine report date (yesterday for weekday, last Friday for Monday) ──
$today = Get-Date
$dow = [int]$today.DayOfWeek
$reportDates = @()

if ($dow -eq 1) {
    # Monday: report Fri + Sat + Sun
    $reportDates += $today.AddDays(-3)  # Fri
    $reportDates += $today.AddDays(-2)  # Sat
    $reportDates += $today.AddDays(-1)  # Sun
} elseif ($dow -eq 0) {
    # Sunday: report Sat
    $reportDates += $today.AddDays(-1)
} else {
    # Tue-Sat: report yesterday
    $reportDates += $today.AddDays(-1)
}

# ── Read scheduler JSONL records ──
$allRecords = @()
foreach ($d in $reportDates) {
    $dateStr = $d.ToString("yyyyMMdd")
    $jsonlPath = Join-Path $logsDir "scheduler_$dateStr.jsonl"
    if (Test-Path $jsonlPath) {
        Get-Content $jsonlPath -Encoding UTF8 | ForEach-Object {
            $line = $_.Trim()
            if ($line) {
                try {
                    $rec = $line | ConvertFrom-Json
                    $allRecords += $rec
                } catch { }
            }
        }
    }
}

# ── Query GitHub Actions results ──
$ghPaths = @(
    "$env:LOCALAPPDATA\Programs\GitHub CLI",
    "C:\Program Files\GitHub CLI"
)
foreach ($p in $ghPaths) {
    if (Test-Path $p) { $env:Path = "$p;$env:Path" }
}

$ghActions = @()
$ghAvailable = $null -ne (Get-Command gh -ErrorAction SilentlyContinue)

if ($ghAvailable) {
    $workflows = @("daily-full.yml", "margin-refresh.yml", "pre-market-alert.yml",
                    "intraday-settlement.yml", "weekly-summary.yml", "heartbeat.yml",
                    "tdcc-weekly.yml", "settlement-tracking.yml")
    foreach ($wf in $workflows) {
        try {
            $runsRaw = & gh run list --repo DRwillychiu/CHIP_RADAR_TW --workflow $wf --limit 3 --json name,status,conclusion,createdAt,updatedAt 2>&1
            $runs = $runsRaw | ConvertFrom-Json
            if ($runs) {
                foreach ($run in $runs) {
                    $createdDate = [datetime]::Parse($run.createdAt).ToLocalTime()
                    $isReportDate = $false
                    foreach ($d in $reportDates) {
                        if ($createdDate.Date -eq $d.Date) { $isReportDate = $true; break }
                    }
                    if ($isReportDate) {
                        $ghActions += @{
                            workflow   = $wf -replace '\.yml$', ''
                            name       = $run.name
                            status     = $run.status
                            conclusion = $run.conclusion
                            time       = $createdDate.ToString("MM/dd HH:mm")
                        }
                    }
                }
            }
        } catch { }
    }
}

# ── Status icons (PS 5.1 safe — no emoji) ──
$ICO_OK   = "[OK]"
$ICO_FAIL = "[FAIL]"
$ICO_SKIP = "[SKIP]"
$ICO_EXC  = "[ERR]"
$ICO_UNK  = "[?]"

# ── Build report text ──
$reportDateLabel = ($reportDates | ForEach-Object { $_.ToString("yyyy/MM/dd (ddd)") }) -join ", "
$sb = New-Object System.Text.StringBuilder

[void]$sb.AppendLine("========================================")
[void]$sb.AppendLine("  Chip Radar TW  --  Daily Report")
[void]$sb.AppendLine("========================================")
[void]$sb.AppendLine("")
[void]$sb.AppendLine("Report date: $reportDateLabel")
[void]$sb.AppendLine("Generated:   $($today.ToString('yyyy/MM/dd HH:mm'))")
[void]$sb.AppendLine("")

# ── Summary stats ──
$okCount   = ($allRecords | Where-Object { $_.status -eq "OK" }).Count
$failCount = ($allRecords | Where-Object { $_.status -eq "FAIL" }).Count
$skipCount = ($allRecords | Where-Object { $_.status -eq "SKIP" }).Count
$excCount  = ($allRecords | Where-Object { $_.status -eq "EXCEPTION" }).Count
$totalCount = $allRecords.Count

if ($totalCount -eq 0 -and $ghActions.Count -eq 0) {
    [void]$sb.AppendLine("[!] No execution records found.")
    [void]$sb.AppendLine("    (possibly a holiday or scheduler not running)")
} else {
    if ($failCount -eq 0 -and $excCount -eq 0 -and $totalCount -gt 0) {
        [void]$sb.AppendLine(">>> ALL PASSED <<<")
    } elseif ($failCount -gt 0 -or $excCount -gt 0) {
        [void]$sb.AppendLine(">>> HAS FAILURES <<<")
    }
    [void]$sb.AppendLine("")

    # ── Local scheduler section ──
    if ($totalCount -gt 0) {
        [void]$sb.AppendLine("--- Local Scheduler ---")
        [void]$sb.AppendLine("  OK: $okCount  |  FAIL: $failCount  |  SKIP: $skipCount  |  ERR: $excCount")
        [void]$sb.AppendLine("")

        $jobGroups = $allRecords | Group-Object -Property job
        foreach ($group in $jobGroups) {
            $jobLabel = $group.Name
            $entries = $group.Group
            [void]$sb.AppendLine("  [$jobLabel]")
            foreach ($e in $entries) {
                $icon = switch ($e.status) {
                    "OK"        { $ICO_OK }
                    "FAIL"      { $ICO_FAIL }
                    "SKIP"      { $ICO_SKIP }
                    "EXCEPTION" { $ICO_EXC }
                    default     { $ICO_UNK }
                }
                $timeStr = ""
                if ($e.ts) {
                    try { $timeStr = ([datetime]::Parse($e.ts)).ToString("MM/dd HH:mm") } catch { }
                }
                $durStr = ""
                if ($e.duration_min -and $e.duration_min -gt 0) {
                    $durStr = " ($($e.duration_min) min)"
                }
                [void]$sb.AppendLine("    $icon $timeStr$durStr")
                if ($e.status -eq "FAIL" -or $e.status -eq "EXCEPTION") {
                    $errDetail = if ($e.error) { $e.error } elseif ($e.output) { $e.output } else { "" }
                    if ($errDetail) {
                        $truncated = if ($errDetail.Length -gt 100) { $errDetail.Substring(0, 100) + "..." } else { $errDetail }
                        [void]$sb.AppendLine("      -> $truncated")
                    }
                }
            }
            [void]$sb.AppendLine("")
        }
    }

    # ── GitHub Actions section ──
    if ($ghActions.Count -gt 0) {
        [void]$sb.AppendLine("--- GitHub Actions ---")
        $ghOk   = ($ghActions | Where-Object { $_.conclusion -eq "success" }).Count
        $ghFail = ($ghActions | Where-Object { $_.conclusion -ne "success" -and $_.conclusion }).Count
        [void]$sb.AppendLine("  OK: $ghOk  |  FAIL: $ghFail")
        [void]$sb.AppendLine("")

        $ghGroups = $ghActions | Group-Object -Property workflow
        foreach ($group in $ghGroups) {
            [void]$sb.AppendLine("  [$($group.Name)]")
            foreach ($run in $group.Group) {
                $icon = if ($run.conclusion -eq "success") { $ICO_OK } else { $ICO_FAIL }
                $concl = if ($run.conclusion) { $run.conclusion } else { $run.status }
                [void]$sb.AppendLine("    $icon $($run.time) $concl")
            }
            [void]$sb.AppendLine("")
        }
    } elseif ($ghAvailable) {
        [void]$sb.AppendLine("--- GitHub Actions ---")
        [void]$sb.AppendLine("  (no runs found for report dates)")
        [void]$sb.AppendLine("")
    } else {
        [void]$sb.AppendLine("--- GitHub Actions ---")
        [void]$sb.AppendLine("  (gh CLI not available)")
        [void]$sb.AppendLine("")
    }
}

$reportText = $sb.ToString()

# ── Display Windows Form dialog ──
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = "Chip Radar - Daily Report"
$form.Size = New-Object System.Drawing.Size(600, 520)
$form.StartPosition = "CenterScreen"
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.TopMost = $true

$textBox = New-Object System.Windows.Forms.TextBox
$textBox.Multiline = $true
$textBox.ReadOnly = $true
$textBox.ScrollBars = "Vertical"
$textBox.Dock = "Fill"
$textBox.Text = $reportText
$textBox.BackColor = [System.Drawing.Color]::FromArgb(30, 30, 30)
$textBox.ForeColor = [System.Drawing.Color]::FromArgb(220, 220, 220)
$textBox.Font = New-Object System.Drawing.Font("Consolas", 10)

$btnPanel = New-Object System.Windows.Forms.Panel
$btnPanel.Dock = "Bottom"
$btnPanel.Height = 45

$btnClose = New-Object System.Windows.Forms.Button
$btnClose.Text = "Close"
$btnClose.Size = New-Object System.Drawing.Size(90, 30)
$btnClose.Location = New-Object System.Drawing.Point(250, 7)
$btnClose.Add_Click({ $form.Close() })

$btnPanel.Controls.Add($btnClose)
$form.Controls.Add($textBox)
$form.Controls.Add($btnPanel)

$form.Add_Shown({ $form.Activate() })
[void]$form.ShowDialog()
