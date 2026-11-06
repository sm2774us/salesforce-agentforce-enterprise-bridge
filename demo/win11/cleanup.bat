@echo off
setlocal enabledelayedexpansion

:: ====================================================================
:: Intelligent Project Root Discovery & Navigation
:: ====================================================================
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\..\.."
set "PROJECT_ROOT=%CD%"
echo [INFO] Working directory set to project root: %PROJECT_ROOT%

echo ==========================================================
echo Starting Salesforce Demo Zero-State Cleanup (Windows)...
echo ==========================================================

:: ====================================================================
:: Intelligent Pre-Check: Detect if environment is already clean
:: ====================================================================
echo [INFO] Scanning Salesforce org for lingering test cases and accounts...

set "CASE_COUNT=0"
for /f "delims=" %%i in ('sf data query --query "SELECT COUNT() FROM Case WHERE Subject LIKE 'bridge-live-%%%%' OR Subject LIKE '%%%%payments:%%%%' OR Subject LIKE '%%%%erp:%%%%' OR Subject LIKE '%%%%telemetry:%%%%' OR Subject LIKE '%%%%Financial review%%%%'" --target-org dev --json ^| findstr /i "totalSize"') do (
    set "LINE=%%i"
    for /f "tokens=2 delims=:," %%a in ("!LINE!") do set "CASE_COUNT=%%a"
)
set "CASE_COUNT=%CASE_COUNT: =%"
if "%CASE_COUNT%"=="" set "CASE_COUNT=0"

set "ACCOUNT_COUNT=0"
for /f "delims=" %%i in ('sf data query --query "SELECT COUNT() FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev --json ^| findstr /i "totalSize"') do (
    set "LINE=%%i"
    for /f "tokens=2 delims=:," %%a in ("!LINE!") do set "ACCOUNT_COUNT=%%a"
)
set "ACCOUNT_COUNT=%ACCOUNT_COUNT: =%"
if "%ACCOUNT_COUNT%"=="" set "ACCOUNT_COUNT=0"

set /a "TOTAL_RECORDS=CASE_COUNT + ACCOUNT_COUNT"

if !TOTAL_RECORDS! EQU 0 (
    echo.
    echo ----------------------------------------------------------
    echo [INFO] CLEANUP ALREADY DONE: Environment is already pristine!
    echo [INFO] Zero matching test cases or demo accounts found.
    echo ----------------------------------------------------------
    goto :purge_artifacts
)

echo [INFO] Found !TOTAL_RECORDS! record(s) to purge. Proceeding with cleanup...
echo.

set "RAND_ID=%RANDOM%"
set "TEMP_CASES=%PROJECT_ROOT%\temp_cases_%RAND_ID%.csv"
set "TEMP_ACCOUNTS=%PROJECT_ROOT%\temp_accounts_%RAND_ID%.csv"

:: 1. Export and delete Cases first
if !CASE_COUNT! GTR 0 (
    echo [1/3] Exporting test Case IDs via bulk export...
    sf data export bulk --query "SELECT Id FROM Case WHERE Subject LIKE 'bridge-live-%%%%' OR Subject LIKE '%%%%payments:%%%%' OR Subject LIKE '%%%%erp:%%%%' OR Subject LIKE '%%%%telemetry:%%%%' OR Subject LIKE '%%%%Financial review%%%%'" --target-org dev --output-file "%TEMP_CASES%" --wait 5 >nul 2>&1

    if exist "%TEMP_CASES%" (
        echo [1/3] Executing bulk delete for Cases...
        sf data delete bulk --sobject Case --file "%TEMP_CASES%" --target-org dev --wait 5 >nul 2>&1
    )
)

echo [INFO] Synchronizing database locks (waiting 2s)...
timeout /t 2 /nobreak >nul

:: 2. Export and delete Accounts robustly via CSV
if !ACCOUNT_COUNT! GTR 0 (
    echo [2/3] Exporting demo Account IDs via bulk export...
    sf data export bulk --query "SELECT Id FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev --output-file "%TEMP_ACCOUNTS%" --wait 5 >nul 2>&1

    if exist "%TEMP_ACCOUNTS%" (
        echo [2/3] Executing bulk delete for demo Accounts...
        sf data delete bulk --sobject Account --file "%TEMP_ACCOUNTS%" --target-org dev --wait 5 >nul 2>&1
    )
)

:purge_artifacts
echo [INFO] Ensuring strict directory hygiene: purging all temporary export artifacts...
timeout /t 2 /nobreak >nul

for %%d in ("%PROJECT_ROOT%" "%SCRIPT_DIR%") do (
    del /f /q /s "%%~d\temp_cases_*" >nul 2>&1
    del /f /q /s "%%~d\temp_accounts_*" >nul 2>&1
    del /f /q /s "%%~d\*.csv" >nul 2>&1
)
echo [INFO] Temporary files successfully wiped.

echo [INFO] Waiting 3 seconds for Salesforce backend replication (syncing indexes)...
timeout /t 3 /nobreak >nul

:: 3. Explicit Verification Query & Zero-State Audit
echo [3/3] Verifying zero-state status in Salesforce ORG...
echo.

set "REMAINING_CASES=0"
for /f "delims=" %%i in ('sf data query --query "SELECT COUNT() FROM Case WHERE Subject LIKE 'bridge-live-%%%%' OR Subject LIKE '%%%%payments:%%%%' OR Subject LIKE '%%%%Financial review%%%%'" --target-org dev --json ^| findstr /i "totalSize"') do (
    set "LINE=%%i"
    for /f "tokens=2 delims=:," %%a in ("!LINE!") do set "REMAINING_CASES=%%a"
)
set "REMAINING_CASES=%REMAINING_CASES: =%"
if "%REMAINING_CASES%"=="" set "REMAINING_CASES=0"

set "REMAINING_ACCOUNTS=0"
for /f "delims=" %%i in ('sf data query --query "SELECT COUNT() FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev --json ^| findstr /i "totalSize"') do (
    set "LINE=%%i"
    for /f "tokens=2 delims=:," %%a in ("!LINE!") do set "REMAINING_ACCOUNTS=%%a"
)
set "REMAINING_ACCOUNTS=%REMAINING_ACCOUNTS: =%"
if "%REMAINING_ACCOUNTS%"=="" set "REMAINING_ACCOUNTS=0"

echo --- Verification Audit Results ---
echo Remaining Demo Cases    : !REMAINING_CASES!
echo Remaining Demo Accounts : !REMAINING_ACCOUNTS!
echo.

if !REMAINING_CASES! EQU 0 if !REMAINING_ACCOUNTS! EQU 0 (
    echo ==========================================================
    echo [ZERO-STATE CONFIRMED] All demo Cases and Accounts purged!
    echo ==========================================================
) else (
    echo ==========================================================
    echo [WARNING] Some records remain. Consider running cleanup again.
    echo ==========================================================
)

popd
endlocal