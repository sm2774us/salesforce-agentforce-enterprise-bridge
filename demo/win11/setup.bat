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
echo SALESFORCE AGENTFORCE ENTERPRISE BRIDGE - ENVIRONMENT SETUP (WIN11)
echo ====================================================================
echo.

:: ====================================================================
:: Step 1: Install Application Dependencies
:: ====================================================================
echo [1/3] Installing application dependencies via make install...
call make install
if errorlevel 1 goto :install_error

echo.
echo ====================================================================
:: Step 2: Intelligent Pre-Check for Existing Records (Idempotent Guard)
:: ====================================================================
echo [2/3] Checking if demo accounts already exist in Salesforce...

set "TEMP_COUNT=%PROJECT_ROOT%\temp_count.json"
call sf data query --query "SELECT COUNT() FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev --json > "%TEMP_COUNT%" 2>&1

set ACCOUNT_COUNT=0
if not exist "%TEMP_COUNT%" goto :evaluate_count

for /f "delims=" %%i in ('type "%TEMP_COUNT%" ^| findstr /i "totalSize"') do (
    set "LINE=%%i"
    for /f "tokens=2 delims=:," %%a in ("!LINE!") do set "ACCOUNT_COUNT=%%a"
)
del /f /q "%TEMP_COUNT%" >nul 2>&1

:evaluate_count
set "ACCOUNT_COUNT=%ACCOUNT_COUNT: =%"
if "%ACCOUNT_COUNT%"=="" set ACCOUNT_COUNT=0

if %ACCOUNT_COUNT% GTR 0 goto :accounts_already_exist
goto :seed_demo_accounts

:accounts_already_exist
echo.
echo ----------------------------------------------------------
echo [INFO] SEEDING ALREADY DONE: Found %ACCOUNT_COUNT% existing demo account(s).
echo [INFO] Skipping account seeding to avoid duplicate entries.
echo [TIP]  Run cleanup.bat first if you want a fresh zero-state setup.
echo ----------------------------------------------------------
goto :verify_accounts

:seed_demo_accounts
echo [INFO] No existing demo accounts found. Seeding sample accounts now...

echo Creating account: Acme Corporation
call sf data create record --sobject Account --values "Name='Acme Corporation' AccountNumber='EXT-Acme-Corporation'" --target-org dev

echo Creating account: Globex Ltd
call sf data create record --sobject Account --values "Name='Globex Ltd' AccountNumber='EXT-Globex-Ltd'" --target-org dev

echo Creating account: Initech
call sf data create record --sobject Account --values "Name='Initech' AccountNumber='EXT-Initech'" --target-org dev

:verify_accounts
echo.
echo ====================================================================
echo [3/3] Verifying active account records in Salesforce...
echo ====================================================================
call sf data query --query "SELECT Id, Name, AccountNumber FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev
goto :success

:install_error
echo.
echo [ERROR] Installation failed. Please check your python/pip environment.
goto :end_script

:success
echo.
echo ====================================================================
echo SETUP COMPLETED SUCCESSFULLY
echo ====================================================================

:end_script
popd
endlocal