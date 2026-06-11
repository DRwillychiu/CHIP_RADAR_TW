# ============================================================================
# check_ps1_syntax.ps1  (v3.33.2, M4)
# PowerShell 腳本語法檢查工具 — 5/22-5/28 事故 (trigger_chip_radar.ps1 L118
# `$verdict:` parse fail → 7 天 silent fail) 的防再發工具。
#
# 為什麼需要: powershell.exe -File 執行前會 parse 整檔, 語法錯誤 = 一行都不跑
#             直接 exit 1, 連 log 第一行都不會寫。Task Scheduler 看起來有觸發,
#             實際 silent fail。改完 .ps1 必跑本工具。
#
# 用法:
#   .\scripts\check_ps1_syntax.ps1                          # 預設檢查桌面 trigger_chip_radar.ps1
#   .\scripts\check_ps1_syntax.ps1 -Path C:\path\to\x.ps1   # 檢查指定腳本
#   .\scripts\check_ps1_syntax.ps1 -Path a.ps1, b.ps1       # 多檔
#
# Exit code: 0 = 全部 PASS, 1 = 有語法錯誤 (可接 CI / 排程)
#
# 注意: 本 repo 刻意不放 trigger_chip_radar.ps1 本體 (含個人路徑, 避免外洩),
#       桌面孤本是運作版, 本工具是它唯一的「版控保護」。
# ============================================================================
param(
    [string[]]$Path = @("$env:USERPROFILE\Desktop\trigger_chip_radar.ps1")
)

$hadError = $false

foreach ($p in $Path) {
    if (-not (Test-Path $p)) {
        Write-Host "SKIP  $p (檔案不存在)" -ForegroundColor Yellow
        continue
    }

    $errors = $null
    $content = Get-Content $p -Raw
    [System.Management.Automation.PSParser]::Tokenize($content, [ref]$errors) | Out-Null

    if ($errors -and $errors.Count -gt 0) {
        $hadError = $true
        Write-Host "FAIL  $p — $($errors.Count) 個語法錯誤:" -ForegroundColor Red
        foreach ($e in $errors) {
            $line = $e.Token.StartLine
            $col  = $e.Token.StartColumn
            Write-Host ("      L{0}:C{1}  {2}" -f $line, $col, $e.Message) -ForegroundColor Red
        }
        Write-Host "      ⚠️ 此腳本用 -File 執行會整檔不跑 (silent fail), 修好前不要部署!" -ForegroundColor Red
    }
    else {
        Write-Host "PASS  $p" -ForegroundColor Green
    }
}

if ($hadError) { exit 1 } else { exit 0 }
