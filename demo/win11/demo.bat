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
echo SALESFORCE AGENTFORCE ENTERPRISE BRIDGE - EXECUTIVE DEMO (WIN11)
echo ====================================================================
echo.

set "AUTO_LAUNCHED=0"

:: ====================================================================
:: Step 1: Liveness & Health Check / Intelligent Auto-Launch
:: Purpose: Checks if bridge server is running. If offline, auto-launches 
:: it with required BRIDGE_API_KEYS and tracks state for cleanup.
:: ====================================================================
echo [1/5] Checking server liveness (/healthz)...
curl -s "http://localhost:8080/healthz" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] BRIDGE SERVER ALREADY RUNNING: Active instance detected on port 8080.
    goto :server_ready
)

echo [INFO] Bridge server not detected on port 8080. Auto-launching Bridge Server...
set "BRIDGE_API_KEYS=agent-key=agent-svc:AGENT,approver-key=jane:APPROVER"
start "Bridge Server" cmd /c "set BRIDGE_API_KEYS=agent-key=agent-svc:AGENT,approver-key=jane:APPROVER && bridge serve --port 8080"
set "AUTO_LAUNCHED=1"

echo [INFO] Waiting 3 seconds for Bridge Server to initialize...
timeout /t 3 /nobreak >nul

curl -s "http://localhost:8080/healthz" >nul 2>&1
if errorlevel 1 goto :server_offline

echo [INFO] Bridge Server successfully launched and responsive!

:server_ready
echo.
curl -s "http://localhost:8080/healthz"
echo.

:: ====================================================================
:: Step 2: Capabilities Discovery & Action Inspection
:: ====================================================================
echo [2/5] Discovering available agent actions...
curl -s "http://localhost:8080/v1/actions" -H "X-API-Key: agent-key" | jq ".[].name"

echo.
echo ====================================================================
:: Step 3: Pre-Event Salesforce State & High-Value Event Submission ($25k)
:: Purpose: Queries Salesforce with properly escaped wildcards (%%%%), 
:: then submits the high-value ERP event triggering the guardrail.
:: ====================================================================
echo [3/5] (Leadership Evidence) Inspecting Salesforce state prior to high-value event...
call sf data query --query "SELECT Id, Subject, Status, Priority FROM Case WHERE Subject LIKE '%%%%Financial review%%%%' OR Priority = 'High' LIMIT 5" --target-org dev

echo.
echo Submitting high-value event ($25,000.00) triggering financial guardrail...
curl -s -X POST "http://localhost:8080/v1/events?wait=true" ^
  -H "X-API-Key: agent-key" ^
  -H "content-type: application/json" ^
  -d "{\"source\":\"erp\",\"account_name\":\"Globex Ltd\",\"severity\":\"high\",\"message\":\"Invoice mismatch\",\"amount_usd\":25000}" | jq

echo.
echo [3/5] (Leadership Evidence) Verifying Salesforce record creation/guardrail hold...
call sf data query --query "SELECT Id, Subject, Status, Priority, Description FROM Case WHERE Subject LIKE '%%%%Financial review%%%%' ORDER BY CreatedDate DESC LIMIT 1" --target-org dev

echo.
echo ====================================================================
:: Step 4: Approval Queue Review, Decision Processing & Post-Approval Check
:: ====================================================================
echo [4/5] Fetching pending approval queue...
curl -s "http://localhost:8080/v1/approvals" -H "X-API-Key: approver-key" | jq

echo Extracting first pending approval ID...
set "APPROVAL_ID="
for /f "delims=" %%i in ('curl -s "http://localhost:8080/v1/approvals" -H "X-API-Key: approver-key" ^| jq -r ".[0].approval_id // empty"') do (
    set "APPROVAL_ID=%%i"
)

if "%APPROVAL_ID%"=="" goto :approval_queue_clear
if "%APPROVAL_ID%"=="null" goto :approval_queue_clear
if "%APPROVAL_ID%"=="empty" goto :approval_queue_clear

echo Processing Approval ID: !APPROVAL_ID!
echo Submitting approval decision (approve: true)...
curl -s -X POST "http://localhost:8080/v1/approvals/%APPROVAL_ID%/decision" ^
  -H "X-API-Key: approver-key" ^
  -H "content-type: application/json" ^
  -d "{\"approve\":true,\"note\":\"verified\"}" | jq

echo.
echo [4/5] (Leadership Evidence) Verifying Salesforce case update post-approval...
call sf data query --query "SELECT Id, Subject, Status FROM Case WHERE Subject LIKE '%%%%Financial review%%%%' ORDER BY LastModifiedDate DESC LIMIT 1" --target-org dev
goto :proceed_step_5

:approval_queue_clear
echo [INFO] Approval queue already clear or no pending holds require processing.

:proceed_step_5
echo.
echo ====================================================================
:: Step 5: Schema Drift Validation, Metrics & Audit Log Inspection
:: ====================================================================
echo [5/5] Testing schema drift handling (expecting HTTP 422 status)...
curl -s -o NUL -w "HTTP Status Code: %%{http_code}\n" -X POST "http://localhost:8080/v1/events" ^
  -H "X-API-Key: agent-key" ^
  -H "content-type: application/json" ^
  -d "{\"bogus\":1}"

echo.
echo System Metrics:
curl -s "http://localhost:8080/metrics"

echo.
echo Latest Audit Log Entry:
curl -s "http://localhost:8080/v1/audit" -H "X-API-Key: agent-key" | jq ".[0]"
goto :success

:server_offline
echo.
echo [ERROR] Server is not reachable at http://localhost:8080 and auto-launch failed. Please start it manually.
goto :end_demo

:success
echo.
echo ====================================================================
echo EXECUTIVE DEMO COMPLETED SUCCESSFULLY
echo ====================================================================

:end_demo
:: Clean up auto-launched bridge server instance if it was started by this script
if "%AUTO_LAUNCHED%"=="1" (
    echo [INFO] Terminating auto-launched Bridge Server instance...
    taskkill /f /im bridge.exe >nul 2>&1
    echo [INFO] Bridge Server stopped cleanly.
)

popd
endlocal