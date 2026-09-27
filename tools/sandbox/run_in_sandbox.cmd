@echo off
rem Runs INSIDE Windows Sandbox only (LogonCommand of the generated .wsb).
rem real_checks.py refuses to run anywhere else (it checks the sandbox account and APEX_SANDBOX=1).
set APEX_SANDBOX=1
set APEX_OUT=C:\apex\out
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
"C:\apex\python\python.exe" "C:\apex\repo\tools\sandbox\real_checks.py" > "C:\apex\out\console.txt" 2>&1
echo %ERRORLEVEL%> "C:\apex\out\DONE.txt"
