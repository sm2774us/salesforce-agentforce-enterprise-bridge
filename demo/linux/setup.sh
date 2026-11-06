#!/usr/bin/env bash
set -euo pipefail

# ====================================================================
# Intelligent Project Root Discovery & Navigation
# ====================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo "===================================================================="
echo "SALESFORCE AGENTFORCE ENTERPRISE BRIDGE - ENVIRONMENT SETUP (LINUX)"
echo "===================================================================="
echo "[INFO] Working directory set to project root: ${PROJECT_ROOT}"
echo

# ====================================================================
# Step 1: Install the Application
# ====================================================================
echo "[1/3] Installing application dependencies via make install..."
if ! make install; then
    echo "[ERROR] Installation failed. Please check your python/pip environment."
    exit 1
fi

echo
echo "===================================================================="
# ====================================================================
# Step 2: Intelligent Pre-Check for Existing Records (Idempotent Guard)
# ====================================================================
echo "[2/3] Checking if demo accounts already exist in Salesforce..."

ACCOUNT_COUNT=$(sf data query --query "SELECT COUNT() FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev --json | jq -r '.result.totalSize // 0')

if [ "${ACCOUNT_COUNT}" -gt 0 ]; then
    echo
    echo "----------------------------------------------------------"
    echo "[INFO] SEEDING ALREADY DONE: Found ${ACCOUNT_COUNT} existing demo account(s)."
    echo "[INFO] Skipping account seeding to avoid duplicate entries."
    echo "[TIP]  Run ./cleanup.sh first if you want a fresh zero-state setup."
    echo "----------------------------------------------------------"
else
    echo "[INFO] No existing demo accounts found. Seeding sample accounts now..."
    
    NAMES=("Acme Corporation" "Globex Ltd" "Initech")
    NUMBERS=("EXT-Acme-Corporation" "EXT-Globex-Ltd" "EXT-Initech")
    
    for i in "${!NAMES[@]}"; do
        name="${NAMES[$i]}"
        acc_num="${NUMBERS[$i]}"
        echo "Creating account: ${name}"
        sf data create record \
          --sobject Account \
          --values "Name='${name}' AccountNumber='${acc_num}'" \
          --target-org dev
    done
fi

echo
echo "===================================================================="
# ====================================================================
# Step 3: Verify Account Status
# ====================================================================
echo "[3/3] Verifying active account records in Salesforce..."
sf data query --query "SELECT Id, Name, AccountNumber FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev

echo
echo "===================================================================="
echo "SETUP COMPLETED SUCCESSFULLY"
echo "===================================================================="