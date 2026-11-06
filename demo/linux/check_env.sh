#!/usr/bin/env bash
set -euo pipefail

# ====================================================================
# Intelligent Project Root Discovery & Navigation
# ====================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo "===================================================================="
echo "SALESFORCE AGENTFORCE ENTERPRISE BRIDGE - PRE-FLIGHT CHECK (LINUX)"
echo "===================================================================="
echo "[INFO] Working directory set to project root: ${PROJECT_ROOT}"
echo

# ====================================================================
# Step 1: Locate and Read .env File
# ====================================================================
ENV_FILE="${PROJECT_ROOT}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo "[ERROR] Environment configuration file not found at: ${ENV_FILE}"
    echo "[TIP]   Copy .env.example to .env and configure your Salesforce & Bridge variables."
    exit 1
fi

echo "[1/4] Loading environment variables from .env..."
while IFS='=' read -r key value || [ -n "$key" ]; do
    [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
    key="$(echo "$key" | xargs)"
    value="$(echo "${value:-}" | tr -d '\r' | xargs)"
    if [ -z "${!key:-}" ]; then
        export "$key"="$value"
    fi
done < "${ENV_FILE}"

SF_LOGIN_URL="${SF_LOGIN_URL:-}"
SF_CLIENT_ID="${SF_CLIENT_ID:-}"
SF_USERNAME="${SF_USERNAME:-}"
SF_PRIVATE_KEY_PATH="${SF_PRIVATE_KEY_PATH:-}"
SF_JWT_AUDIENCE="${SF_JWT_AUDIENCE:-}"

echo "[INFO] SF_LOGIN_URL          : ${SF_LOGIN_URL}"
echo "[INFO] SF_CLIENT_ID          : ${SF_CLIENT_ID}"
echo "[INFO] SF_USERNAME           : ${SF_USERNAME}"
echo "[INFO] SF_PRIVATE_KEY_PATH   : ${SF_PRIVATE_KEY_PATH}"
echo "[INFO] SF_JWT_AUDIENCE       : ${SF_JWT_AUDIENCE}"
echo

# ====================================================================
# Step 2: Validate Required Environment Configurations & Resolve Path
# ====================================================================
echo "[2/4] Validating required configuration fields & resolving paths..."

MISSING=0
if [ -z "${SF_LOGIN_URL}" ]; then
    echo "[ERROR] SF_LOGIN_URL is missing or empty in .env"
    MISSING=1
fi
if [ -z "${SF_CLIENT_ID}" ]; then
    echo "[ERROR] SF_CLIENT_ID is missing or empty in .env"
    MISSING=1
fi
if [ -z "${SF_USERNAME}" ]; then
    echo "[ERROR] SF_USERNAME is missing or empty in .env"
    MISSING=1
fi
if [ -z "${SF_PRIVATE_KEY_PATH}" ]; then
    echo "[ERROR] SF_PRIVATE_KEY_PATH is missing or empty in .env"
    MISSING=1
fi

if [ "${MISSING}" -eq 1 ]; then
    echo
    echo "===================================================================="
    echo "[PRE-FLIGHT FAILED] Critical .env parameters are unconfigured."
    echo "===================================================================="
    exit 1
fi

# Intelligent Path Resolution: Handle ./ relative paths vs absolute paths
ABS_KEY_PATH="${SF_PRIVATE_KEY_PATH}"
if [[ "${SF_PRIVATE_KEY_PATH}" == ./* ]]; then
    ABS_KEY_PATH="${PROJECT_ROOT}/${SF_PRIVATE_KEY_PATH#./}"
elif [[ "${SF_PRIVATE_KEY_PATH}" != /* ]]; then
    ABS_KEY_PATH="${PROJECT_ROOT}/${SF_PRIVATE_KEY_PATH}"
fi

echo "[INFO] Resolved Private Key Path : ${ABS_KEY_PATH}"
if [ ! -f "${ABS_KEY_PATH}" ]; then
    echo "[ERROR] Private key file not found at resolved location: ${ABS_KEY_PATH}"
    echo "[TIP]   Ensure server.key exists in the ./secrets/ directory of your project root."
    exit 1
fi

echo "[INFO] Configuration validation passed. Key file verified."
echo

# ====================================================================
# Step 3: Generate JWT Bearer Assertion Payload via Python
# ====================================================================
echo "[3/4] Generating JWT Bearer assertion payload..."

if ! python -c "import jwt, datetime; print('Python JWT module loaded successfully')" 2>&1; then
    echo "[ERROR] Python 'jwt' or 'cryptography' module is not installed!"
    echo "[TIP]   Run: pip install pyjwt cryptography"
    exit 1
fi

JWT_ASSERTION=$(python -c "import jwt, datetime; print(jwt.encode({'iss': '${SF_CLIENT_ID}', 'sub': '${SF_USERNAME}', 'aud': '${SF_LOGIN_URL}', 'exp': int((datetime.datetime.utcnow() + datetime.timedelta(minutes=3)).timestamp())}, open('${ABS_KEY_PATH}').read(), algorithm='RS256'))")

if [ -z "${JWT_ASSERTION}" ]; then
    echo "[ERROR] Failed to generate JWT token assertion payload."
    exit 1
fi

echo "[INFO] JWT Bearer assertion generated successfully."
echo

# ====================================================================
# Step 4: Test Salesforce OAuth Handshake & Token Retrieval
# ====================================================================
echo "[4/4] Executing Salesforce OAuth2 JWT Bearer token handshake..."

TOKEN_RESPONSE="${PROJECT_ROOT}/temp_oauth_resp_$$.json"
trap 'rm -f "${TOKEN_RESPONSE}" 2>/dev/null || true' EXIT

curl -s -X POST "${SF_LOGIN_URL}/services/oauth2/token" \
  -d "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer" \
  -d "assertion=${JWT_ASSERTION}" > "${TOKEN_RESPONSE}"

echo
echo "--- OAuth Handshake Response Schema ---"
jq "keys" "${TOKEN_RESPONSE}" 2>/dev/null || cat "${TOKEN_RESPONSE}"

echo
if grep -q "access_token" "${TOKEN_RESPONSE}"; then
    echo "===================================================================="
    echo "[PRE-FLIGHT SUCCESS] Salesforce Playground & .env integration verified!"
    echo "[INFO] Valid access token issued by Salesforce connected app."
    echo "===================================================================="
    exit 0
else
    echo "===================================================================="
    echo "[PRE-FLIGHT FAILED] OAuth Token exchange rejected by Salesforce!"
    echo "[TIP] Verify Connected App pre-authorization, Client ID, and Private Key certificate."
    echo "===================================================================="
    exit 1
fi