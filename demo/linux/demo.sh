#!/usr/bin/env bash
set -euo pipefail

# ====================================================================
# Intelligent Project Root Discovery & Navigation
# ====================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

echo "===================================================================="
echo "SALESFORCE AGENTFORCE ENTERPRISE BRIDGE - EXECUTIVE DEMO (LINUX)"
echo "===================================================================="
echo "[INFO] Working directory set to project root: ${PROJECT_ROOT}"
echo

BRIDGE_PID=""
AUTO_LAUNCHED=0

# Comprehensive cleanup function to terminate auto-launched server on exit
cleanup_server() {
    if [ "${AUTO_LAUNCHED}" -eq 1 ] && [ -n "${BRIDGE_PID}" ]; then
        echo
        echo "[INFO] Terminating auto-launched Bridge Server (PID: ${BRIDGE_PID})..."
        kill "${BRIDGE_PID}" 2>/dev/null || kill -9 "${BRIDGE_PID}" 2>/dev/null || true
        echo "[INFO] Bridge Server stopped cleanly."
    fi
}
trap cleanup_server EXIT

# ====================================================================
# Step 1: Liveness & Health Check / Intelligent Auto-Launch
# Purpose: Checks if bridge server is running. If offline, auto-launches 
# it in the background and tracks its PID.
# ====================================================================
echo "[1/5] Checking server liveness (/healthz)..."
if curl -s "http://localhost:8080/healthz" > /dev/null 2>&1; then
    echo "[INFO] BRIDGE SERVER ALREADY RUNNING: Active instance detected on port 8080."
else
    echo "[INFO] Bridge server not detected on port 8080. Auto-launching Bridge Server..."
    export BRIDGE_API_KEYS="agent-key=agent-svc:AGENT,approver-key=jane:APPROVER"
    
    bridge serve --port 8080 &
    BRIDGE_PID=$!
    AUTO_LAUNCHED=1

    echo "[INFO] Waiting 3 seconds for Bridge Server to initialize (PID: ${BRIDGE_PID})..."
    sleep 3

    if ! curl -s "http://localhost:8080/healthz" > /dev/null 2>&1; then
        echo "[ERROR] Failed to auto-launch the Bridge Server. Please start it manually."
        exit 1
    fi
    echo "[INFO] Bridge Server successfully launched and responsive!"
fi

curl -s "http://localhost:8080/healthz"
echo -e "\n"

# ====================================================================
# Step 2: Capabilities Discovery & Action Inspection
# ====================================================================
echo "[2/5] Discovering available agent actions..."
curl -s "http://localhost:8080/v1/actions" -H "X-API-Key: agent-key" | jq -r '.[].name'

echo
echo "===================================================================="
# ====================================================================
# Step 3: Pre-Event Salesforce State & High-Value Event Submission ($25k)
# ====================================================================
echo "[3/5] (Leadership Evidence) Inspecting Salesforce state prior to high-value event..."
sf data query --query "SELECT Id, Subject, Status, Priority FROM Case WHERE Subject LIKE '%Financial review%' OR Priority = 'High' LIMIT 5" --target-org dev

echo
echo "Submitting high-value event (\$25,000.00) triggering financial guardrail..."
curl -s -X POST "http://localhost:8080/v1/events?wait=true" \
  -H "X-API-Key: agent-key" \
  -H "content-type: application/json" \
  -d '{"source":"erp","account_name":"Globex Ltd","severity":"high","message":"Invoice mismatch","amount_usd":25000}' | jq

echo
echo "[3/5] (Leadership Evidence) Verifying Salesforce record creation/guardrail hold..."
sf data query --query "SELECT Id, Subject, Status, Priority, Description FROM Case WHERE Subject LIKE '%Financial review%' ORDER BY CreatedDate DESC LIMIT 1" --target-org dev

echo
echo "===================================================================="
# ====================================================================
# Step 4: Approval Queue Review, Decision Processing & Post-Approval Check
# ====================================================================
echo "[4/5] Fetching pending approval queue..."
curl -s "http://localhost:8080/v1/approvals" -H "X-API-Key: approver-key" | jq

echo "Extracting first pending approval ID..."
APPROVAL_ID=$(curl -s "http://localhost:8080/v1/approvals" -H "X-API-Key: approver-key" | jq -r '.[0].approval_id // empty')

if [ -z "${APPROVAL_ID}" ] || [ "${APPROVAL_ID}" = "null" ] || [ "${APPROVAL_ID}" = "empty" ]; then
    echo "[INFO] Approval queue already clear or no pending holds require processing. Skipping decision step."
else
    echo "Processing Approval ID: ${APPROVAL_ID}"

    echo "Submitting approval decision (approve: true)..."
    curl -s -X POST "http://localhost:8080/v1/approvals/${APPROVAL_ID}/decision" \
      -H "X-API-Key: approver-key" \
      -H "content-type: application/json" \
      -d '{"approve":true,"note":"verified"}' | jq

    echo
    echo "[4/5] (Leadership Evidence) Verifying Salesforce case update post-approval..."
    sf data query --query "SELECT Id, Subject, Status FROM Case WHERE Subject LIKE '%Financial review%' ORDER BY LastModifiedDate DESC LIMIT 1" --target-org dev
fi

echo
echo "===================================================================="
# ====================================================================
# Step 5: Schema Drift Validation, Metrics & Audit Log Inspection
# ====================================================================
echo "[5/5] Testing schema drift handling (expecting HTTP 422 status)..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://localhost:8080/v1/events" \
  -H "X-API-Key: agent-key" \
  -H "content-type: application/json" \
  -d '{"bogus":1}')
echo "HTTP Status Code: ${HTTP_CODE}"

echo
echo "System Metrics:"
curl -s "http://localhost:8080/metrics"

echo -e "\n"
echo "Latest Audit Log Entry:"
curl -s "http://localhost:8080/v1/audit" -H "X-API-Key: agent-key" | jq '.[0]'

echo
echo "===================================================================="
echo "EXECUTIVE DEMO COMPLETED SUCCESSFULLY"
echo "===================================================================="