$ErrorActionPreference = "Stop"

function Assert-Equal {
    param(
        [string]$Name,
        [int]$Expected,
        [int]$Actual
    )
    if ($Actual -ne $Expected) {
        throw "[FAIL] $Name expected=$Expected actual=$Actual"
    }
    Write-Host "[PASS] $Name => $Actual"
}

function Assert-AtLeast {
    param(
        [string]$Name,
        [int]$Threshold,
        [int]$Actual
    )
    if ($Actual -lt $Threshold) {
        throw "[FAIL] $Name expected-at-least=$Threshold actual=$Actual"
    }
    Write-Host "[PASS] $Name => $Actual"
}

function Count-InFile {
    param(
        [string]$Pattern,
        [string]$Path,
        [switch]$IsRegex
    )

    if (Get-Command rg -ErrorAction SilentlyContinue) {
        if ($IsRegex) {
            return (rg -n --glob $Path $Pattern | Measure-Object).Count
        }
        return (rg --fixed-strings -n $Pattern $Path | Measure-Object).Count
    }

    if (-not (Test-Path $Path)) {
        return 0
    }

    if ($IsRegex) {
        return (Select-String -Path $Path -Pattern $Pattern -Encoding UTF8 | Measure-Object).Count
    }
    return (Select-String -Path $Path -SimpleMatch -Pattern $Pattern -Encoding UTF8 | Measure-Object).Count
}

$registerCount = (Get-ChildItem -Recurse -Filter main.py | Select-String -SimpleMatch '@register(' -Encoding UTF8 | Measure-Object).Count
Assert-Equal -Name 'register-decorator-count' -Expected 1 -Actual $registerCount

$senderDefCount = Count-InFile -Pattern 'def extract_sender(' -Path 'ctf_plugin/utils.py'
Assert-Equal -Name 'extract-sender-def-count' -Expected 1 -Actual $senderDefCount

$windowRuleCount = Count-InFile -Pattern 'lower_bound < delta_minutes <= win' -Path 'ctf_plugin/scheduler_manager.py'
Assert-AtLeast -Name 'window-crossing-rule' -Threshold 1 -Actual $windowRuleCount

$atomicSaveCount = Count-InFile -Pattern 'os.replace(tmp_path, self.subscriptions_path)' -Path 'ctf_plugin/scheduler_manager.py'
Assert-AtLeast -Name 'atomic-save' -Threshold 1 -Actual $atomicSaveCount

$unsubscribeMethodCount = Count-InFile -Pattern 'def cmd_unsubscribe(' -Path 'main.py'
Assert-Equal -Name 'unsubscribe-command-handler' -Expected 1 -Actual $unsubscribeMethodCount

$listMethodCount = Count-InFile -Pattern 'def cmd_subscription_list(' -Path 'main.py'
Assert-Equal -Name 'list-command-handler' -Expected 1 -Actual $listMethodCount

Write-Host ""
Write-Host "OK: subscription-fix structure checks passed"
