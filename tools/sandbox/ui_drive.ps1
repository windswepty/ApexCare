<#
.SYNOPSIS
  샌드박스 점검(real_checks.py)이 설치 마법사·제거 프로그램 창을 누르는 데 쓰는 UI 자동화 도우미.

.DESCRIPTION
  Windows UI Automation 으로 제목이 -Window 정규식과 맞는 최상위 창을 찾아, 이름이 -Name 정규식과 맞는
  컨트롤에 -Action 을 한다. 결과는 항상 JSON 한 줄이다: {"ok":bool,"error":"...","names":[...]}
  names 는 실패했을 때 창 안에서 보인 컨트롤 이름들이다(무엇이 달랐는지 보고서에서 알 수 있게).

  읽기와 버튼 누르기만 한다. 설치 프로그램에 무인 설치용 숨은 옵션을 만들지 않으려고 이렇게 창을 누른다.

  -Action
    exists   창이 있는지 (Name 은 쓰지 않음)
    click    버튼 누르기 (InvokePattern)
    select   라디오 버튼 고르기 (SelectionItemPattern)
    uncheck  체크 상자 끄기 (TogglePattern, 이미 꺼져 있으면 그대로)
    wait     이름이 맞는 컨트롤이 나타날 때까지 기다리기만
    names    창 안의 컨트롤 이름 목록만
#>
param(
    [Parameter(Mandatory = $true)][string]$Window,
    [Parameter(Mandatory = $true)][ValidateSet('exists', 'wait', 'click', 'select', 'uncheck', 'names')][string]$Action,
    [string]$Name = '',
    [int]$TimeoutSec = 30
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$AE = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$True_ = [System.Windows.Automation.Condition]::TrueCondition

function Emit([bool]$ok, [string]$err, $names) {
    $o = [ordered]@{ ok = $ok; error = $err; names = @($names) }
    Write-Output (ConvertTo-Json -InputObject $o -Compress -Depth 3)
}

function Find-Window {
    foreach ($w in $AE::RootElement.FindAll($Scope::Children, $True_)) {
        try { if ($w.Current.Name -match $Window) { return $w } } catch {}
    }
    return $null
}

function Control-Names($win) {
    $names = New-Object System.Collections.ArrayList
    foreach ($e in $win.FindAll($Scope::Descendants, $True_)) {
        try {
            $n = $e.Current.Name
            if ($n) { [void]$names.Add(('{0}: {1}' -f $e.Current.ControlType.ProgrammaticName, $n)) }
        } catch {}
    }
    return $names
}

# 이름만 맞춰 찾으면 '[종료]를 클릭하십시오' 같은 안내 글이 먼저 걸린다. 동작에 맞는 패턴을 지원하는 컨트롤만 고른다.
$needPattern = @{
    click   = $AE::IsInvokePatternAvailableProperty
    select  = $AE::IsSelectionItemPatternAvailableProperty
    uncheck = $AE::IsTogglePatternAvailableProperty
}

function Find-Control($win) {
    $prop = $needPattern[$Action]
    foreach ($e in $win.FindAll($Scope::Descendants, $True_)) {
        try {
            if ($e.Current.Name -match $Name -and $e.Current.IsEnabled) {
                if (-not $prop -or $e.GetCurrentPropertyValue($prop)) { return $e }
            }
        } catch {}
    }
    return $null
}

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$win = $null
$ctl = $null
do {
    $win = Find-Window
    if ($win) {
        if ($Action -in 'exists', 'names') { break }
        $ctl = Find-Control $win
        if ($ctl) { break }
    }
    Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)

if (-not $win) { Emit $false "창을 찾지 못했습니다: $Window" @(); exit 0 }
if ($Action -eq 'exists') { Emit $true '' @(); exit 0 }
if ($Action -eq 'names') { Emit $true '' (Control-Names $win); exit 0 }
if (-not $ctl) { Emit $false "컨트롤을 찾지 못했습니다: $Name" (Control-Names $win); exit 0 }

try {
    switch ($Action) {
        'wait' { }
        'click' {
            $ctl.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        }
        'select' {
            $ctl.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
        }
        'uncheck' {
            $tp = $ctl.GetCurrentPattern([System.Windows.Automation.TogglePattern]::Pattern)
            if ($tp.Current.ToggleState -eq [System.Windows.Automation.ToggleState]::On) { $tp.Toggle() }
        }
    }
    Emit $true '' @()
} catch {
    Emit $false ("{0} 실패: {1}" -f $Action, $_.Exception.Message) (Control-Names $win)
}
