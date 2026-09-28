<#
.SYNOPSIS
  APEX CARE 가 바꿀 수 있는 시스템 상태를 텍스트 파일로 떠 둔다. 읽기만 하고 아무것도 바꾸지 않는다.

.DESCRIPTION
  실제 Windows 점검(docs/windows-manual-checklist.md)에서 기능을 적용하기 전과 되돌린 뒤의 상태를
  비교하는 데 쓴다. 두 파일이 같으면 원래대로 돌아온 것이다.

  담는 것: 전원 플랜(활성·목록·성능 모드가 바꾸는 세부값 AC/DC), 레지스트리(MMCSS, 원격 분석·Cortana 정책,
  HwSchMode, 어댑터별 Nagle), 서비스 시작 유형(SysMain·WSearch·DiagTrack), TCP 전역 설정,
  시작 프로그램 Run 키와 APEX CARE 가 꺼 둔 목록, 디블로터 대상 Appx, APEX CARE 저널·설정 파일 요약.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\snapshot_state.ps1 -Out C:\apex\before.txt
  (기능 적용 → 되돌리기)
  powershell -ExecutionPolicy Bypass -File tools\snapshot_state.ps1 -Out C:\apex\after.txt
  Compare-Object (Get-Content C:\apex\before.txt) (Get-Content C:\apex\after.txt)
  → 아무것도 나오지 않으면 원래대로 돌아온 것이다.
#>
param([Parameter(Mandatory = $true)][string]$Out)

$ErrorActionPreference = 'Continue'
$lines = New-Object System.Collections.Generic.List[string]
function Line([string]$s) { $lines.Add($s) }

function RegValue([string]$path, [string]$name) {
    try {
        $v = (Get-ItemProperty -LiteralPath $path -Name $name -ErrorAction Stop).$name
        if ($v -is [array]) { return ($v -join ',') }
        return "$v"
    } catch { return '<없음>' }
}

function RegAllValues([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { Line "  <키 없음>"; return }
    $item = Get-Item -LiteralPath $path
    $names = @($item.GetValueNames() | Sort-Object)
    if ($names.Count -eq 0) { Line "  <값 없음>"; return }
    foreach ($n in $names) {
        $v = $item.GetValue($n, $null, 'DoNotExpandEnvironmentNames')
        if ($v -is [byte[]]) { $v = 'hex:' + (($v | ForEach-Object { $_.ToString('x2') }) -join '') }
        Line ("  {0} = {1}" -f $n, $v)
    }
}

# ── 전원 ───────────────────────────────────────────
$SUB_PROCESSOR = '54533251-82be-4824-96c1-47b60b740d00'
$SUB_USB = '2a737441-1930-4402-8d77-b2bebba308a3'
$POWER_SETTINGS = @(
    @($SUB_PROCESSOR, '893dee8e-2bef-41e0-89c6-b55d0929964c', 'CPU 최소 속도(PROCTHROTTLEMIN)'),
    @($SUB_PROCESSOR, 'bc5038f7-23e0-4960-96da-33abaf5935ec', 'CPU 최대 속도(PROCTHROTTLEMAX)'),
    @($SUB_PROCESSOR, '0cc5b647-c1df-4637-891a-dec35c318583', '코어 파킹(CPMINCORES)'),
    @($SUB_USB, '48e6b7a6-50f5-4782-a5d4-53bb8f07e226', 'USB 선택적 절전'),
    @($SUB_PROCESSOR, 'be337238-0d82-4146-a960-4f3749d470c7', 'CPU 부스트 모드(PERFBOOSTMODE)'),
    @($SUB_PROCESSOR, '36687f9e-e3a5-4dbf-b1dc-15eb381c6863', 'CPU 성능/효율 선호(PERFEPP)'),
    @('501a4d13-42af-4429-9fd1-a8218c268e20', 'ee12f906-d277-404b-b6da-e5fa1a576df5', 'PCIe 절전(ASPM)')
)
$guidRe = '[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'

Line '[전원] 활성 플랜'
$active = [regex]::Match((powercfg /getactivescheme | Out-String), $guidRe).Value.ToLower()
Line "  $active"

Line '[전원] 플랜 목록'
$plans = @()
foreach ($l in (powercfg /list)) {
    $m = [regex]::Match($l, $guidRe)
    if ($m.Success) {
        $plans += $m.Value.ToLower()
        Line ("  " + $l.Trim().Replace('*', '').Trim())
    }
}

Line '[전원] 플랜별 세부값 (AC / DC, 16진수)'
foreach ($p in ($plans | Sort-Object)) {
    foreach ($s in $POWER_SETTINGS) {
        $qh = powercfg /qh $p $s[0] $s[1] 2>$null       # $out 은 안 된다: PowerShell 변수는 대소문자를 가리지 않아 -Out 을 덮어쓴다
        $ac = '?'; $dc = '?'
        foreach ($l in $qh) {
            $m = [regex]::Match($l, '\b(AC|DC)\b.*:\s*(0x[0-9a-fA-F]+)')
            if ($m.Success) { if ($m.Groups[1].Value -eq 'AC') { $ac = $m.Groups[2].Value } else { $dc = $m.Groups[2].Value } }
        }
        Line ("  {0}  {1}: AC={2} DC={3}" -f $p, $s[2], $ac, $dc)
    }
}

# ── 레지스트리 ─────────────────────────────────────
Line '[레지스트리]'
$MM = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile'
$regs = @(
    @($MM, 'SystemResponsiveness'),
    @($MM, 'NetworkThrottlingIndex'),
    @('HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection', 'AllowTelemetry'),
    @('HKLM:\SOFTWARE\Policies\Microsoft\Windows\Windows Search', 'AllowCortana'),
    @('HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers', 'HwSchMode')
)
foreach ($r in $regs) { Line ("  {0}\{1} = {2}" -f $r[0], $r[1], (RegValue $r[0] $r[1])) }

Line '[레지스트리] 어댑터별 Nagle (TcpAckFrequency / TCPNoDelay)'
$ifRoot = 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces'
foreach ($k in (Get-ChildItem -LiteralPath $ifRoot -ErrorAction SilentlyContinue | Sort-Object PSChildName)) {
    $p = "$ifRoot\$($k.PSChildName)"
    Line ("  {0}: TcpAckFrequency={1} TCPNoDelay={2}" -f $k.PSChildName, (RegValue $p 'TcpAckFrequency'), (RegValue $p 'TCPNoDelay'))
}

# ── 서비스 ─────────────────────────────────────────
Line '[서비스] 시작 유형 (Start: 2 자동, 3 수동, 4 사용 안 함 / DelayedAutostart)'
foreach ($svc in 'SysMain', 'WSearch', 'DiagTrack') {
    $p = "HKLM:\SYSTEM\CurrentControlSet\Services\$svc"
    Line ("  {0}: Start={1} DelayedAutostart={2}" -f $svc, (RegValue $p 'Start'), (RegValue $p 'DelayedAutostart'))
}

# ── TCP 전역 ───────────────────────────────────────
Line '[네트워크] netsh int tcp show global'
foreach ($l in (netsh int tcp show global)) { if ($l.Trim() -and $l -match ':') { Line ("  " + $l.Trim()) } }

# ── 시작 프로그램 ──────────────────────────────────
foreach ($rk in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
                  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run',
                  'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Run',
                  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run',
                  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run',
                  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32',
                  'HKCU:\Software\APEXCARE\DisabledStartup',
                  'HKCU:\Software\APEXCARE\DisabledStartup\_origin')) {
    Line "[시작 프로그램] $rk"
    RegAllValues $rk
}

# ── Appx (디블로터 대상과, 건드리면 안 되는 Xbox 게임 바·새 Xbox 앱) ──
Line '[Appx] 현재 사용자에게 설치된 대상 패키지'
$patterns = '*bing*', '*zune*', '*solitaire*', '*skypeapp*', '*windowsmaps*', '*yourphone*',
            '*3dbuilder*', '*feedbackhub*', '*xboxapp*', 'Microsoft.XboxGamingOverlay', 'Microsoft.GamingApp'
$found = @()
foreach ($pat in $patterns) {
    try { $found += @(Get-AppxPackage -Name $pat -ErrorAction Stop | ForEach-Object { $_.Name }) } catch { }
}
if ($found.Count -eq 0) { Line '  <없음>' } else { foreach ($n in ($found | Sort-Object -Unique)) { Line "  $n" } }

# ── APEX CARE 자체 기록 ────────────────────────────
$data = Join-Path $env:APPDATA 'APEX_CARE_DATA'
Line "[APEX CARE] 저널 $data\system_state.json"
$jp = Join-Path $data 'system_state.json'
if (Test-Path -LiteralPath $jp) {
    try {
        $j = Get-Content -LiteralPath $jp -Raw -Encoding UTF8 | ConvertFrom-Json
        $keys = @($j.entries.PSObject.Properties | ForEach-Object { "{0} (group={1})" -f $_.Name, $_.Value.group } | Sort-Object)
        Line "  항목 $($keys.Count)개"
        foreach ($k in $keys) { Line "  $k" }
    } catch { Line "  <읽지 못함: $($_.Exception.Message)>" }
} else { Line '  <파일 없음>' }

Line "[APEX CARE] 설정 $data\settings.json"
$sp = Join-Path $data 'settings.json'
if (Test-Path -LiteralPath $sp) {
    try {
        $s = Get-Content -LiteralPath $sp -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($k in 'optimization_mode', 'optimization_mode_user_set', 'booster_enabled', 'boost_restore_mode',
                       'boost_disable_nagle', 'boost_auto_power_mode', 'setup_wizard_done') {
            $v = $s.$k
            Line ("  {0} = {1}" -f $k, $(if ($null -eq $v) { '<없음>' } else { $v }))
        }
        foreach ($k in 'network_tweak_backup', 'service_start_backup') {
            Line ("  {0} = {1}" -f $k, $(if ($null -eq $s.$k) { '<없음>' } else { '<있음>' }))
        }
    } catch { Line "  <읽지 못함: $($_.Exception.Message)>" }
} else { Line '  <파일 없음>' }

$dir = Split-Path -Parent $Out
if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
$lines | Set-Content -LiteralPath $Out -Encoding UTF8
Write-Host "상태를 저장했습니다: $Out ($($lines.Count)줄)"
