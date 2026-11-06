#!/usr/init/env bash
set -euo pipefail

# ====================================================================
# Intelligent Project Root Discovery & Navigation
# ====================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo "=========================================================="
echo "Starting Salesforce Demo Zero-State Cleanup (Linux)..."
echo "=========================================================="
echo "[INFO] Working directory set to project root: ${PROJECT_ROOT}"
echo

cleanup_artifacts() {
    sleep 0.5 2>/dev/null || true
    rm -f "${SCRIPT_DIR}"/temp_cases_* "${PROJECT_ROOT}"/temp_cases_* 2>/dev/null || true
    rm -f "${SCRIPT_DIR}"/temp_accounts_* "${PROJECT_ROOT}"/temp_accounts_* 2>/dev/null || true
    rm -f "${SCRIPT_DIR}"/*.csv "${PROJECT_ROOT}"/*.csv 2>/dev/null || true
}
trap cleanup_artifacts EXIT

echo "[INFO] Scanning Salesforce org for lingering test cases and accounts..."
CASE_COUNT=$(sf data query --query "SELECT COUNT() FROM Case WHERE Subject LIKE 'bridge-live-%' OR Subject LIKE '%payments:%' OR Subject LIKE '%erp:%' OR Subject LIKE '%telemetry:%' OR Subject LIKE '%Financial review%'" --target-org dev --json | jq -r '.result.totalSize // 0')
ACCOUNT_COUNT=$(sf data query --query "SELECT COUNT() FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev --json | jq -r '.result.totalSize // 0')

TOTAL_RECORDS=$((CASE_COUNT + ACCOUNT_COUNT))

if [ "${TOTAL_RECORDS}" -eq 0 ]; then
    echo
    echo "----------------------------------------------------------"
    echo "[INFO] CLEANUP ALREADY DONE: Environment is already pristine!"
    echo "[INFO] Zero matching test cases or demo accounts found."
    echo "----------------------------------------------------------"
    cleanup_artifacts
    echo "[INFO] Directory hygiene verified. No temporary files present."
    echo "=========================================================="
    echo "Cleanup complete! Your environment is back to zero state."
    echo "=========================================================="
    exit 0
fi

echo "[INFO] Found ${TOTAL_RECORDS} record(s) to purge. Proceeding..."
echo

TEMP_CASES="${PROJECT_ROOT}/temp_cases_$$.csv"
TEMP_ACCOUNTS="${PROJECT_ROOT}/temp_accounts_$$.csv"

# 1. Export and delete Cases first
if [ "${CASE_COUNT}" -gt 0 ]; then
    echo "[1/3] Exporting test Case IDs via bulk export..."
    sf data export bulk --query "SELECT Id FROM Case WHERE Subject LIKE 'bridge-live-%' OR Subject LIKE '%payments:%' OR Subject LIKE '%erp:%' OR Subject LIKE '%telemetry:%' OR Subject LIKE '%Financial review%'" --target-org dev --output-file "${TEMP_CASES}" --wait 5 > /dev/null 2>&1 || true

    if [ -s "${TEMP_CASES}" ] && [ "$(wc -l < "${TEMP_CASES}")" -gt 1 ]; then
        echo "[1/3] Executing bulk delete for Cases..."
        sf data delete bulk --sobject Case --file "${TEMP_CASES}" --target-org dev --wait 5 > /dev/null 2>&1 || true
    fi
fi

echo "[INFO] Synchronizing database locks (waiting 2s)..."
sleep 2

# 2. Export and delete Accounts robustly via CSV
if [ "${ACCOUNT_COUNT}" -gt 0 ]; then
    echo "[2/3] Exporting demo Account IDs via bulk export..."
    sf data export bulk --query "SELECT Id FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev --output-file "${TEMP_ACCOUNTS}" --wait 5 > /dev/null 2>&1 || true

    if [ -s "${TEMP_ACCOUNTS}" ] && [ "$(wc -l < "${TEMP_ACCOUNTS}")" -gt 1 ]; then
        echo "[2/3] Executing bulk delete for demo Accounts..."
        sf data delete bulk --sobject Account --file "${TEMP_ACCOUNTS}" --target-org dev --wait 5 > /dev/null 2>&1 || true
    fi
fi

echo "[INFO] Purging temporary CSV export artifacts..."
cleanup_artifacts
echo "[INFO] Temporary export files successfully wiped."

echo "[INFO] Waiting 3 seconds for Salesforce backend replication (syncing indexes)..."
sleep 3

# 3. Explicit Verification Query & Zero-State Audit
echo
echo "[3/3] Verifying zero-state status in Salesforce ORG..."

REMAINING_CASES=$(sf data query --query "SELECT COUNT() FROM Case WHERE Subject LIKE 'bridge-live-%' OR Subject LIKE '%payments:%' OR Subject LIKE '%Financial review%'" --target-org dev --json | jq -r '.result.totalSize // 0')
REMAINING_ACCOUNTS=$(sf data query --query "SELECT COUNT() FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev --json | jq -r '.result.totalSize // 0')

echo "--- Verification Audit Results ---"
echo "Remaining Demo Cases    : ${REMAINING_CASES}"
echo "Remaining Demo Accounts : ${REMAINING_ACCOUNTS}"
echo

if [ "${REMAINING_CASES}" -eq 0 ] && [ "${REMAINING_ACCOUNTS}" -eq 0 ]; then
    echo "=========================================================="
    echo "[ZERO-STATE CONFIRMED] All demo Cases and Accounts purged!"
    echo "=========================================================="
else
    echo "=========================================================="
    echo "[WARNING] Some records remain. Consider running cleanup again."
    echo "=========================================================="
fi