<#
.SYNOPSIS
  Windows 샌드박스를 띄워 실제 Windows 점검(tools/sandbox/real_checks.py)을 자동으로 돌린다.

.DESCRIPTION
  개발 PC 는 바꾸지 않는다. 샌드박스는 닫으면 안의 변경이 전부 사라지는 일회용 Windows 다.
  저장소와 파이썬 폴더, 설치 파일 폴더(dist, 있으면)는 읽기 전용으로, 결과 폴더만 쓰기 가능으로 넘기고 네트워크는 끈다.
  dist 에 설치 파일이 있으면 설치 마법사 → 제거 프로그램 점검도 돈다(없으면 그 점검만 건너뜀).
  샌드박스가 켜지면 real_checks.py 가 알아서 돌고, 결과를 결과 폴더의 report.md 에 남긴다.

  준비(한 번만, 관리자 PowerShell, 재부팅 필요):
    Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\sandbox\start_sandbox_check.ps1 -Wait
#>
param(
    [string]$Out = (Join-Path $env:TEMP ('apexcare-sandbox-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))),
    [string]$Dist = '',
    [switch]$Wait,
    [int]$TimeoutMin = 40
)

$exe = Join-Path $env:SystemRoot 'System32\WindowsSandbox.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    Write-Host 'Windows 샌드박스가 켜져 있지 않습니다. 관리자 PowerShell 에서 아래를 실행하고 재부팅하세요:'
    Write-Host '  Enable-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -All'
    exit 2
}
if (Get-Process -Name WindowsSandbox, WindowsSandboxClient -ErrorAction SilentlyContinue) {
    Write-Host '샌드박스가 이미 열려 있습니다. 한 번에 하나만 띄울 수 있으니 닫고 다시 실행하세요.'
    exit 2
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host 'python 을 찾지 못했습니다.'; exit 2 }
$pyDir = Split-Path -Parent $py.Source
if (-not (Test-Path -LiteralPath (Join-Path $pyDir 'Lib\site-packages\psutil'))) {
    Write-Host "psutil 이 $pyDir 에 없습니다. pip install -r requirements-dev.txt 후 다시 실행하세요."
    exit 2
}

if (-not $Dist) { $Dist = Join-Path $repo 'dist' }
$distMap = ''
if (Test-Path -LiteralPath $Dist) {
    $distMap = "    <MappedFolder><HostFolder>$([System.Security.SecurityElement]::Escape((Resolve-Path -LiteralPath $Dist).Path))</HostFolder><SandboxFolder>C:\apex\dist</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>`n"
} else {
    Write-Host "설치 파일 폴더($Dist)가 없어 설치·제거 프로그램 점검은 건너뜁니다."
}

New-Item -ItemType Directory -Force -Path $Out | Out-Null
# 지난 실행의 결과가 남아 있으면 -Wait 가 샌드박스가 뜨기도 전에 그것을 이번 결과로 돌려준다. 띄우기 전에 지운다.
foreach ($name in 'DONE.txt', 'report.md', 'report.json', 'console.txt', 'snap') {
    $p = Join-Path $Out $name
    if (Test-Path -LiteralPath $p) {
        try { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop }
        catch { Write-Host "지난 결과($p)를 지우지 못했습니다. 다른 결과 폴더를 쓰세요."; exit 2 }
    }
}
$esc = { param($s) [System.Security.SecurityElement]::Escape($s) }
$wsb = Join-Path $Out 'apexcare-check.wsb'
$xml = @"
<Configuration>
  <Networking>Disable</Networking>
  <MappedFolders>
    <MappedFolder><HostFolder>$(& $esc $repo)</HostFolder><SandboxFolder>C:\apex\repo</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$(& $esc $pyDir)</HostFolder><SandboxFolder>C:\apex\python</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>$(& $esc $Out)</HostFolder><SandboxFolder>C:\apex\out</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
$distMap  </MappedFolders>
  <LogonCommand><Command>C:\apex\repo\tools\sandbox\run_in_sandbox.cmd</Command></LogonCommand>
</Configuration>
"@
[System.IO.File]::WriteAllText($wsb, $xml, (New-Object System.Text.UTF8Encoding($false)))

Start-Process -FilePath $exe -ArgumentList "`"$wsb`""
Write-Host "샌드박스를 띄웠습니다. 결과 폴더: $Out"
Write-Host '점검이 끝나면 결과 폴더에 DONE.txt 와 report.md 가 생깁니다. 샌드박스 창은 확인 뒤 닫으면 됩니다.'

if ($Wait) {
    $deadline = (Get-Date).AddMinutes($TimeoutMin)
    while (-not (Test-Path -LiteralPath (Join-Path $Out 'DONE.txt'))) {
        if ((Get-Date) -gt $deadline) { Write-Host "$TimeoutMin 분 안에 끝나지 않았습니다."; exit 3 }
        Start-Sleep -Seconds 10
    }
    Get-Content -LiteralPath (Join-Path $Out 'report.md') -Encoding UTF8
    $code = (Get-Content -LiteralPath (Join-Path $Out 'DONE.txt')).Trim()
    exit [int]$code
}
