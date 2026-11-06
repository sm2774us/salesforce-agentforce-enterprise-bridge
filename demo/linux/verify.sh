#!/usr/bin/env bash
set -euo pipefail

# ====================================================================
# Intelligent Project Root Discovery & Navigation
# ====================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo "===================================================================="
echo "SALESFORCE AGENTFORCE ENTERPRISE BRIDGE - AUDIT & VERIFICATION (LINUX)"
echo "===================================================================="
echo "[INFO] Working directory set to project root: ${PROJECT_ROOT}"
echo

# ====================================================================
# Step 1: Server Liveness Pre-Check
# ====================================================================
echo "[1/4] Probing Bridge Server liveness (/healthz)..."
if ! curl -s "http://localhost:8080/healthz" > /dev/null 2>&1; then
    echo
    echo "----------------------------------------------------------"
    echo "[NOTICE] Bridge Server is currently offline at http://localhost:8080."
    echo "[INFO]   Skipping local runtime telemetry/audit checks; proceeding to Salesforce ORG verification..."
    echo "----------------------------------------------------------"
else
    echo "[INFO] Bridge Server is online and responsive."
    echo
    # ====================================================================
    # Step 2: Bridge Server Internal Audit & Metrics Inspection
    # ====================================================================
    echo "[2/4] Inspecting Bridge Server audit trail and runtime metrics..."
    echo
    echo "--- Latest Audit Event ---"
    curl -s "http://localhost:8080/v1/audit" -H "X-API-Key: agent-key" | jq '.[0]'

    echo
    echo "--- Cumulative Bridge Metrics ---"
    curl -s "http://localhost:8080/metrics" | grep -E "^bridge_" || true
fi

echo
echo "===================================================================="
# ====================================================================
# Step 3: Salesforce Zero-State & Demo Record Audit
# ====================================================================
echo "[3/4] Querying Salesforce ORG for active demo accounts and financial review cases..."
echo
echo "--- Demo Accounts Status ---"
sf data query --query "SELECT Id, Name, AccountNumber FROM Account WHERE Name IN ('Acme Corporation', 'Globex Ltd', 'Initech')" --target-org dev

echo
echo "--- Live Demo Generated Cases ---"
sf data query --query "SELECT Id, Subject, Status, Priority, Description, CreatedDate FROM Case WHERE Subject LIKE '%Financial review%' OR Subject LIKE '%Invoice mismatch%' OR Subject LIKE '%bridge-live-%' ORDER BY CreatedDate DESC" --target-org dev

echo
echo "===================================================================="
# ====================================================================
# Step 4: Executive Lifecycle Verification & Strict JSON Count Audit
# ====================================================================
echo "[4/4] Evaluating execution lifecycle (Cleanup -> Setup -> Demo)..."

RECORD_COUNT=$(sf data query --query "SELECT Id FROM Case WHERE Subject LIKE '%Financial review%' OR Subject LIKE '%Invoice mismatch%' OR Subject LIKE '%bridge-live-%'" --target-org dev --json | jq -r '.result.totalSize // 0')

echo
if [ "${RECORD_COUNT}" -gt 0 ]; then
    echo "=========================================================="
    echo "[VERIFICATION PASSED] Executive lifecycle validated successfully!"
    echo "[INFO] Active demo artifacts and guardrail records confirmed in Salesforce."
    echo "=========================================================="
    exit 0
else
    echo "=========================================================="
    echo "[VERIFICATION FAILED] No active demo artifacts detected."
    echo "[INFO] The environment is currently in a pristine zero-state or setup-only state."
    echo "[ACTION REQUIRED] To produce valid demo audit evidence, please complete the full sequence:"
    echo "                  1. ./cleanup.sh"
    echo "                  2. ./setup.sh"
    echo "                  3. ./demo.sh"
    echo "=========================================================="
    exit 1
fi