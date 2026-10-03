@echo off
rem Runs INSIDE Windows Sandbox only (LogonCommand of the generated .wsb).
rem real_checks.py refuses to run anywhere else (it checks the sandbox account and APEX_SANDBOX=1).
set APEX_SANDBOX=1
set APEX_OUT=C:\apex\out
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
rem Append: after the reboot check this file runs again and the console log must keep the first part.
"C:\apex\python\python.exe" "C:\apex\repo\tools\sandbox\real_checks.py" >> "C:\apex\out\console.txt" 2>&1
set RC=%ERRORLEVEL%
rem 50 = reboot check. Restart the sandbox; the LogonCommand runs this file again after the restart and
rem real_checks.py continues from reboot_state.json. Only the sandbox account may restart (never a real PC).
if /i "%USERNAME%"=="WDAGUtilityAccount" if "%RC%"=="50" shutdown /r /t 5
if "%RC%"=="50" exit /b 0
rem Redirect first: "echo 1> file" would treat "1>" as a stream redirect and write "ECHO is off."
> "C:\apex\out\DONE.txt" echo %RC%
rem Close the sandbox when done. A sandbox left open keeps files in the mapped folders (dist) open,
rem and the next build_all.bat then fails to write the exe. Only the sandbox account may shut down:
rem if this file is ever run on a real PC it must never turn that PC off.
if /i "%USERNAME%"=="WDAGUtilityAccount" if exist "C:\apex\out\DONE.txt" shutdown /s /t 20
