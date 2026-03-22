$ErrorActionPreference = "Stop"

function Assert-Equal {
    param([string]$Name, [int]$Expected, [int]$Actual)
    if ($Actual -ne $Expected) {
        throw "[FAIL] $Name expected=$Expected actual=$Actual"
    }
    Write-Host "[PASS] $Name => $Actual"
}

function Assert-AtLeast {
    param([string]$Name, [int]$Min, [int]$Actual)
    if ($Actual -lt $Min) {
        throw "[FAIL] $Name expected-at-least=$Min actual=$Actual"
    }
    Write-Host "[PASS] $Name => $Actual"
}

function Count-Pattern {
    param([string]$Path, [string]$Pattern)
    if (-not (Test-Path $Path)) {
        return 0
    }
    return (Select-String -Path $Path -SimpleMatch -Pattern $Pattern -Encoding UTF8 | Measure-Object).Count
}

$ctfplusFileExists = (Test-Path "ctf_plugin/data_sources/ctfplus.py")
if ($ctfplusFileExists) {
    throw "[FAIL] ctfplus.py still exists"
}
Write-Host "[PASS] ctfplus.py removed"

Assert-Equal -Name 'ctfplus-import-in-main' -Expected 0 -Actual (Count-Pattern -Path "main.py" -Pattern "CTFPlusSource")
Assert-Equal -Name 'ctfplus-command-exists' -Expected 0 -Actual (Count-Pattern -Path "main.py" -Pattern '@filter.command("ctf+")')
Assert-Equal -Name 'ctfplus-method-exists' -Expected 0 -Actual (Count-Pattern -Path "ctf_plugin/data_sources/aggregator.py" -Pattern "fetch_ctfplus_only")
Assert-Equal -Name 'ctfplus-default-config' -Expected 0 -Actual (Count-Pattern -Path "ctf_plugin/config_manager.py" -Pattern '"ctfplus"')
Assert-Equal -Name 'bs4-dependency' -Expected 0 -Actual (Count-Pattern -Path "requirements.txt" -Pattern "beautifulsoup4")
Assert-AtLeast -Name 'event-query-service-exists' -Min 1 -Actual (Count-Pattern -Path "ctf_plugin/data_sources/aggregator.py" -Pattern "class EventQueryService")
Assert-Equal -Name 'main-uses-old-aggregator-field' -Expected 0 -Actual (Count-Pattern -Path "main.py" -Pattern "self.aggregator")
Assert-AtLeast -Name 'main-uses-query-service-field' -Min 1 -Actual (Count-Pattern -Path "main.py" -Pattern "self.query_service")

Assert-AtLeast -Name 'ctftime-command-kept' -Min 1 -Actual (Count-Pattern -Path "main.py" -Pattern '@filter.command("ctftime")')
Assert-AtLeast -Name 'subscribe-command-kept' -Min 1 -Actual (Count-Pattern -Path "main.py" -Pattern 'def cmd_subscribe(')
Assert-AtLeast -Name 'unsubscribe-command-kept' -Min 1 -Actual (Count-Pattern -Path "main.py" -Pattern 'def cmd_unsubscribe(')
Assert-AtLeast -Name 'subscription-list-command-kept' -Min 1 -Actual (Count-Pattern -Path "main.py" -Pattern 'def cmd_subscription_list(')

Write-Host ""
Write-Host "OK: CTFTime-only refactor checks passed"
