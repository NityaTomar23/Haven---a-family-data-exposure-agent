#!/usr/bin/env bash
# Proves Haven's deny-by-default egress boundary.
#
# STATUS: AUTHORED AND NEVER RUN. OpenShell requires Linux (Landlock ABI v3,
# i.e. Linux 6.2+) plus Docker 28.0+, and this checkout was prepared on
# Windows 11 without WSL or Docker. Do not describe this test as passing until
# it has actually run and its output is committed under docs/. The script
# refuses to report success on any ambiguous result for exactly that reason.
#
# What it checks, in order:
#
#   1. POSITIVE CONTROL -- an allowlisted host must be reachable. Without this,
#      a sandbox with no network at all would "pass" the negative test for the
#      wrong reason.
#   2. NEGATIVE TEST -- a host that is not in the allowlist must fail. The
#      probe runs through python3, which IS an allowlisted binary, so a failure
#      cannot be blamed on a missing executable; it is a policy denial.
#   3. PROVER, candidate -- policy/policy.yaml must be within_boundary.
#   4. PROVER, counterexample -- policy/counterexample.yaml must be
#      exceeds_boundary, which proves the prover actually discriminates rather
#      than rubber-stamping everything.
#
# Only `within_boundary` counts as a pass for step 3. `unsupported`,
# `inconclusive`, and `error` all count as failures.
#
# Usage:
#     policy/boundary_test.sh [sandbox-name]
#
# Environment:
#     HAVEN_SANDBOX       sandbox name (default: haven)
#     HAVEN_ALLOWED_HOST  allowlisted host for the positive control
#                         (default: api.tavily.com)
#     HAVEN_DENIED_HOST   host that must be denied (default: example.com)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX="${1:-${HAVEN_SANDBOX:-haven}}"
ALLOWED_HOST="${HAVEN_ALLOWED_HOST:-api.tavily.com}"
DENIED_HOST="${HAVEN_DENIED_HOST:-example.com}"
DOCS_DIR="${REPO_ROOT}/docs"

PASSED=0
FAILED=0

pass() { printf 'PASS  %s\n' "$1"; PASSED=$((PASSED + 1)); }
fail() { printf 'FAIL  %s\n' "$1"; FAILED=$((FAILED + 1)); }
info() { printf '      %s\n' "$1"; }

# ── Probe program ──────────────────────────────────────────────────────
# Deliberately uses no double quotes so it can be passed as a single
# argument to `python3 -c`.
read -r -d '' PROBE <<'PY' || true
import socket, ssl, sys
host = sys.argv[1]
try:
    with socket.create_connection((host, 443), timeout=15) as raw:
        with ssl.create_default_context().wrap_socket(raw, server_hostname=host):
            pass
except Exception as exc:
    print('BLOCKED %s: %s: %s' % (host, type(exc).__name__, exc))
    raise SystemExit(1)
print('REACHED %s' % host)
PY

probe() {
    # Returns 0 when the sandbox reached the host, non-zero otherwise.
    openshell sandbox exec -n "$SANDBOX" --no-login-shell -- \
        python3 -c "$PROBE" "$1" 2>&1
}

# ── Preflight ──────────────────────────────────────────────────────────
printf 'Haven egress boundary test\n'
printf 'sandbox: %s\n\n' "$SANDBOX"

for binary in openshell openshell-prover; do
    if ! command -v "$binary" >/dev/null 2>&1; then
        printf 'FAIL  %s is not on PATH.\n' "$binary"
        info 'OpenShell requires Linux with Landlock ABI v3 (Linux 6.2+) and'
        info 'Docker 28.0+. Install it, then re-run this script.'
        exit 2
    fi
done

if ! openshell sandbox get "$SANDBOX" >/dev/null 2>&1; then
    printf 'FAIL  sandbox %s not found.\n' "$SANDBOX"
    info "Create it first, e.g.:"
    info "  openshell sandbox create --name $SANDBOX \\"
    info "    --policy $REPO_ROOT/policy/policy.hardened.yaml -- /bin/bash"
    exit 2
fi

# ── 1. Positive control ────────────────────────────────────────────────
printf '[1/4] positive control: %s must be reachable\n' "$ALLOWED_HOST"
if probe "$ALLOWED_HOST"; then
    pass "allowlisted egress to $ALLOWED_HOST works"
else
    fail "allowlisted egress to $ALLOWED_HOST failed"
    info 'The negative test below would pass vacuously. Fix this first:'
    info 'check that the host is allowlisted in the policy that the sandbox'
    info 'was created with, and that the probe binary path matches the'
    info 'interpreter actually running (see the *PROVER-SAFE* note in'
    info 'policy/policy.yaml).'
fi

# ── 2. Negative test ───────────────────────────────────────────────────
printf '\n[2/4] negative test: %s must be denied\n' "$DENIED_HOST"
denied_output="$(probe "$DENIED_HOST")"
denied_status=$?
if [ "$denied_status" -ne 0 ]; then
    pass "egress to $DENIED_HOST was blocked"
    info "$(printf '%s' "$denied_output" | head -n 1)"
else
    fail "egress to $DENIED_HOST was NOT blocked -- deny-by-default is broken"
fi

# ── 3. Prover: the candidate must be within the boundary ───────────────
printf '\n[3/4] policy prover: policy.yaml vs boundary.yaml\n'
mkdir -p "$DOCS_DIR"
candidate_json="$DOCS_DIR/policy-prover-policy.json"
if openshell-prover check "$REPO_ROOT/policy/policy.yaml" \
        --boundary "$REPO_ROOT/policy/boundary.yaml" \
        --output json >"$candidate_json" 2>&1; then
    result="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["result"])' "$candidate_json" 2>/dev/null || echo unreadable)"
    if [ "$result" = "within_boundary" ]; then
        pass "policy.yaml is within_boundary"
    else
        fail "expected within_boundary, got '$result'"
        info "see $candidate_json"
    fi
else
    result="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("result","unreadable"))' "$candidate_json" 2>/dev/null || echo unreadable)"
    fail "prover did not pass: result='$result' (only within_boundary passes)"
    info "see $candidate_json"
fi

# ── 4. Prover: the counterexample must exceed the boundary ─────────────
printf '\n[4/4] prover discriminates: counterexample.yaml must exceed\n'
counter_json="$DOCS_DIR/policy-prover-counterexample.json"
openshell-prover check "$REPO_ROOT/policy/counterexample.yaml" \
    --boundary "$REPO_ROOT/policy/boundary.yaml" \
    --output json >"$counter_json" 2>&1
counter_status=$?
counter_result="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("result","unreadable"))' "$counter_json" 2>/dev/null || echo unreadable)"
if [ "$counter_status" -eq 1 ] && [ "$counter_result" = "exceeds_boundary" ]; then
    pass "counterexample correctly rejected as exceeds_boundary"
    info "$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get("counterexample",""))' "$counter_json" 2>/dev/null)"
else
    fail "expected exceeds_boundary with exit 1, got '$counter_result' (exit $counter_status)"
    info 'If this fails, the prover cannot discriminate and step 3 proves nothing.'
    info "see $counter_json"
fi

# ── Summary ────────────────────────────────────────────────────────────
printf '\n%s passed, %s failed\n' "$PASSED" "$FAILED"
if [ "$FAILED" -gt 0 ]; then
    printf 'BOUNDARY NOT PROVEN\n'
    exit 1
fi
printf 'BOUNDARY PROVEN\n'
exit 0
