@echo off
setlocal enabledelayedexpansion

:: ====================================================================
:: Intelligent Project Root Discovery & Environment Navigation
:: ====================================================================
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%\..\.."
set "PROJECT_ROOT=%CD%"

echo ====================================================================
echo SALESFORCE AGENTFORCE ENTERPRISE BRIDGE - PRE-FLIGHT CHECK (WIN11)
echo ====================================================================
echo [INFO] Working directory set to project root: %PROJECT_ROOT%
echo.

:: ====================================================================
:: Step 1: Locate and Read .env File
:: ====================================================================
set "ENV_FILE=%PROJECT_ROOT%\.env"
if not exist "%ENV_FILE%" (
    echo [ERROR] Environment configuration file not found at: %ENV_FILE%
    echo [TIP]   Copy .env.example to .env and configure your Salesforce ^& Bridge variables.
    popd
    endlocal
    exit /b 1
)

echo [1/4] Loading environment variables from .env...
for /f "usebackq tokens=1* delims==" %%A in ("%ENV_FILE%") do (
    set "KEY=%%A"
    set "VAL=%%B"
    if not "!KEY!"=="" if not "!KEY:~0,1!"=="#" (
        for /f "tokens=*" %%k in ("!KEY!") do set "KEY=%%k"
        if not "!VAL!"=="" (
            for /f "tokens=*" %%v in ("!VAL!") do set "VAL=%%v"
            if "!KEY!"=="SF_LOGIN_URL" if "%SF_LOGIN_URL%"=="" set "SF_LOGIN_URL=!VAL!"
            if "!KEY!"=="SF_CLIENT_ID" if "%SF_CLIENT_ID%"=="" set "SF_CLIENT_ID=!VAL!"
            if "!KEY!"=="SF_USERNAME" if "%SF_USERNAME%"=="" set "SF_USERNAME=!VAL!"
            if "!KEY!"=="SF_PRIVATE_KEY_PATH" if "%SF_PRIVATE_KEY_PATH%"=="" set "SF_PRIVATE_KEY_PATH=!VAL!"
            if "!KEY!"=="SF_JWT_AUDIENCE" if "%SF_JWT_AUDIENCE%"=="" set "SF_JWT_AUDIENCE=!VAL!"
        )
    )
)

echo [INFO] SF_LOGIN_URL          : %SF_LOGIN_URL%
echo [INFO] SF_CLIENT_ID          : %SF_CLIENT_ID%
echo [INFO] SF_USERNAME           : %SF_USERNAME%
echo [INFO] SF_PRIVATE_KEY_PATH   : %SF_PRIVATE_KEY_PATH%
echo [INFO] SF_JWT_AUDIENCE       : %SF_JWT_AUDIENCE%
echo.

:: ====================================================================
:: Step 2: Validate Required Environment Configurations & Resolve Path
:: ====================================================================
echo [2/4] Validating required configuration fields & resolving paths...

if "%SF_LOGIN_URL%"=="" (
    echo [ERROR] SF_LOGIN_URL is missing or empty in .env
    goto :preflight_failed
)
if "%SF_CLIENT_ID%"=="" (
    echo [ERROR] SF_CLIENT_ID is missing or empty in .env
    goto :preflight_failed
)
if "%SF_USERNAME%"=="" (
    echo [ERROR] SF_USERNAME is missing or empty in .env
    goto :preflight_failed
)
if "%SF_PRIVATE_KEY_PATH%"=="" (
    echo [ERROR] SF_PRIVATE_KEY_PATH is missing or empty in .env
    goto :preflight_failed
)

:: Normalize forward slashes to backslashes
set "NORM_KEY_PATH=%SF_PRIVATE_KEY_PATH:/=\%"

:: Intelligent Path Resolution: Handle relative paths from project root vs absolute paths
set "ABS_KEY_PATH=%NORM_KEY_PATH%"
if "%NORM_KEY_PATH:~0,2%"==".\\" (
    set "ABS_KEY_PATH=%PROJECT_ROOT%%NORM_KEY_PATH:~1%"
) else if not "%NORM_KEY_PATH:~1,1%"==":" (
    set "ABS_KEY_PATH=%PROJECT_ROOT%\%NORM_KEY_PATH%"
)

echo [INFO] Resolved Private Key Path : %ABS_KEY_PATH%
if not exist "%ABS_KEY_PATH%" (
    echo [ERROR] Private key file not found at resolved location: %ABS_KEY_PATH%
    echo [TIP]   Ensure server.key exists in the ./secrets/ directory of your project root.
    goto :preflight_failed
)

echo [INFO] Configuration validation passed. Key file verified.
echo.

:: ====================================================================
:: Step 3: Generate JWT Bearer Assertion Payload via Python
:: ====================================================================
echo [3/4] Generating JWT Bearer assertion payload...

python -c "import jwt, datetime; print('Python JWT module loaded successfully')"
if errorlevel 1 (
    echo [ERROR] Python 'jwt' or 'cryptography' module is not installed!
    echo [TIP]   Run: pip install pyjwt cryptography
    goto :preflight_failed
)

set "JWT_ASSERTION="
for /f "tokens=*" %%i in ('python -c "import jwt, datetime; print(jwt.encode({'iss': '%SF_CLIENT_ID%', 'sub': '%SF_USERNAME%', 'aud': '%SF_LOGIN_URL%', 'exp': int((datetime.datetime.utcnow() + datetime.timedelta(minutes=3)).timestamp())}, open(r'%ABS_KEY_PATH%').read(), algorithm='RS256'))"') do set "JWT_ASSERTION=%%i"

if "%JWT_ASSERTION%"=="" (
    echo [ERROR] Failed to generate JWT token assertion payload.
    goto :preflight_failed
)

echo [INFO] JWT Bearer assertion generated successfully.
echo.

:: ====================================================================
:: Step 4: Test Salesforce OAuth Handshake & Token Retrieval
:: ====================================================================
echo [4/4] Executing Salesforce OAuth2 JWT Bearer token handshake...

set "TOKEN_RESPONSE=%PROJECT_ROOT%\temp_oauth_resp.json"
curl -s -X POST "%SF_LOGIN_URL%/services/oauth2/token" ^
  -d "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer" ^
  -d "assertion=%JWT_ASSERTION%" > "%TOKEN_RESPONSE%"

echo.
echo --- OAuth Handshake Response Schema ---
type "%TOKEN_RESPONSE%" | jq "keys" 2>nul
if errorlevel 1 type "%TOKEN_RESPONSE%"

echo.
findstr /i "access_token" "%TOKEN_RESPONSE%" >nul 2>&1
if not errorlevel 1 (
    echo ====================================================================
    echo [PRE-FLIGHT SUCCESS] Salesforce Playground ^& .env integration verified!
    echo [INFO] Valid access token issued by Salesforce connected app.
    echo ====================================================================
    if exist "%TOKEN_RESPONSE%" del /f /q "%TOKEN_RESPONSE%" >nul 2>&1
    popd
    endlocal
    exit /b 0
) else (
    echo ====================================================================
    echo [PRE-FLIGHT FAILED] OAuth Token exchange rejected by Salesforce!
    echo [TIP] Verify Connected App pre-authorization, Client ID, and Private Key certificate.
    echo ====================================================================
    if exist "%TOKEN_RESPONSE%" del /f /q "%TOKEN_RESPONSE%" >nul 2>&1
    popd
    endlocal
    exit /b 1
)

:preflight_failed
echo.
echo ====================================================================
echo [PRE-FLIGHT FAILED] Environment verification did not pass.
echo ====================================================================
popd
endlocal
exit /b 1