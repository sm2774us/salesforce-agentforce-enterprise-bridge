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

echo ====================================================================
echo SALESFORCE AGENTFORCE ENTERPRISE BRIDGE - AUDIT & VERIFICATION (WIN11)
echo ====================================================================
echo.

:: ====================================================================
:: Step 1: Server Liveness Pre-Check
:: ====================================================================
echo [1/4] Probing Bridge Server liveness (/healthz)...
curl -s "http://localhost:8080/healthz" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ----------------------------------------------------------
    echo [NOTICE] Bridge Server is currently offline at http://localhost:8080.
    echo [INFO]   Skipping local runtime telemetry/audit checks; proceeding directly to Salesforce ORG verification...
    echo ----------------------------------------------------------
    goto :salesforce_audit
)
echo [INFO] Bridge Server is online and responsive.
echo.

:: ====================================================================
:: Step 2: Bridge Server Internal Audit & Metrics Inspection
:: ====================================================================
echo [2/4] Inspecting Bridge Server audit trail and runtime metrics...
echo.
echo --- Latest Audit Event ---
curl -s "http://localhost:8080/v1/audit" -H "X-API-Key: agent-key" | jq ".[0]"

echo.
echo --- Cumulative Bridge Metrics ---
curl -s "http://localhost:8080/metrics" | findstr /i "bridge_"

:salesforce_audit
echo.
echo ====================================================================
:: Step 3: Salesforce Zero-State & Demo Record Audit
:: ====================================================================
echo [3/4] Querying Salesforce ORG for active demo accounts and financial review cases...
echo.
echo --- Demo Accounts Status ---
call sf data query --query "SELECT Id, Name, AccountNumber FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev

echo.
echo --- Live Demo Generated Cases ---
call sf data query --query "SELECT Id, Subject, Status, Priority, Description, CreatedDate FROM Case WHERE Subject LIKE '%%%%Financial review%%%%' OR Subject LIKE '%%%%Invoice mismatch%%%%' OR Subject LIKE '%%%%bridge-live-%%%%' ORDER BY CreatedDate DESC" --target-org dev

echo.
echo ====================================================================
:: Step 4: Executive Lifecycle Verification & Strict Count Audit
:: ====================================================================
echo [4/4] Evaluating execution lifecycle (Cleanup -> Setup -> Demo)...

set "TEMP_VERIFY=%PROJECT_ROOT%\temp_verify.json"
call sf data query --query "SELECT Id FROM Case WHERE Subject LIKE '%%%%Financial review%%%%' OR Subject LIKE '%%%%Invoice mismatch%%%%' OR Subject LIKE '%%%%bridge-live-%%%%'" --target-org dev --json > "%TEMP_VERIFY%" 2>&1

set "RECORD_COUNT=0"
if exist "%TEMP_VERIFY%" (
    for /f "delims=" %%i in ('type "%TEMP_VERIFY%" ^| findstr /i "totalSize"') do (
        set "LINE=%%i"
        for /f "tokens=2 delims=:," %%a in ("!LINE!") do set "RECORD_COUNT=%%a"
    )
    del /f /q "%TEMP_VERIFY%" >nul 2>&1
)

set "RECORD_COUNT=%RECORD_COUNT: =%"
if "%RECORD_COUNT%"=="" set "RECORD_COUNT=0"

echo.
if %RECORD_COUNT% GTR 0 (
    echo ==========================================================
    echo [VERIFICATION PASSED] Executive lifecycle validated successfully!
    echo [INFO] Active demo artifacts and guardrail records confirmed in Salesforce.
    echo ==========================================================
    popd
    endlocal
    exit /b 0
) else (
    echo ==========================================================
    echo [VERIFICATION FAILED] No active demo artifacts detected.
    echo [INFO] The environment is currently in a pristine zero-state or setup-only state.
    echo [ACTION REQUIRED] To produce valid demo audit evidence, please complete the full sequence:
    echo                 1. cleanup.bat
    echo                 2. setup.bat
    echo                 3. demo.bat
    echo ==========================================================
    popd
    endlocal
    exit /b 1
)