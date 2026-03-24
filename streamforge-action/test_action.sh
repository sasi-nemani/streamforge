#!/bin/bash
# Tests for the StreamForge GitHub Action.
# Run from the streamforge-action/ directory:
#   bash test_action.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0
FAIL=0

_ok() {
    echo "PASS: $1"
    PASS=$((PASS + 1))
}

_fail() {
    echo "FAIL: $1"
    FAIL=$((FAIL + 1))
}

# ---------------------------------------------------------------------------
# Test 1: action.yml is valid YAML
# ---------------------------------------------------------------------------
python3 -c "
import yaml, sys
with open('${SCRIPT_DIR}/action.yml') as f:
    data = yaml.safe_load(f)
assert data is not None, 'action.yml parsed to None'
assert 'name' in data, 'action.yml missing name key'
assert 'inputs' in data, 'action.yml missing inputs key'
assert 'runs' in data, 'action.yml missing runs key'
" && _ok "action.yml is valid YAML" || _fail "action.yml is not valid YAML"

# ---------------------------------------------------------------------------
# Test 2: entrypoint.sh exists and has correct shebang
# ---------------------------------------------------------------------------
ENTRYPOINT="${SCRIPT_DIR}/entrypoint.sh"
if [ -f "${ENTRYPOINT}" ]; then
    SHEBANG=$(head -1 "${ENTRYPOINT}")
    if [ "${SHEBANG}" = "#!/bin/bash" ]; then
        _ok "entrypoint.sh has correct shebang (#!/bin/bash)"
    else
        _fail "entrypoint.sh shebang is '${SHEBANG}' (expected #!/bin/bash)"
    fi
else
    _fail "entrypoint.sh does not exist"
fi

# ---------------------------------------------------------------------------
# Test 3: entrypoint.sh is executable
# ---------------------------------------------------------------------------
if [ -x "${ENTRYPOINT}" ]; then
    _ok "entrypoint.sh is executable"
else
    _fail "entrypoint.sh is not executable (run: chmod +x entrypoint.sh)"
fi

# ---------------------------------------------------------------------------
# Test 4: action.yml has optional brokers and topic inputs (zero-config support)
# ---------------------------------------------------------------------------
python3 -c "
import yaml
with open('${SCRIPT_DIR}/action.yml') as f:
    data = yaml.safe_load(f)
inputs = data.get('inputs', {})
optional_inputs = ['brokers', 'topic']
for inp in optional_inputs:
    assert inp in inputs, f'Missing input: {inp}'
    assert inputs[inp].get('required') is False or inputs[inp].get('required') is None or inputs[inp].get('required') == '', \
        f'Input {inp} should be required=false (got {inputs[inp].get(\"required\")})'
" && _ok "action.yml has optional brokers and topic inputs (zero-config)" || _fail "action.yml brokers/topic should be required=false"

# ---------------------------------------------------------------------------
# Test 4b: entrypoint.sh has auto-discovery logic
# ---------------------------------------------------------------------------
if grep -q 'find.*schema.yaml' "${ENTRYPOINT}"; then
    _ok "entrypoint.sh has auto-discovery find schemas/ logic"
else
    _fail "entrypoint.sh missing auto-discovery find schemas/ logic"
fi

# ---------------------------------------------------------------------------
# Test 5: action.yml defines expected outputs
# ---------------------------------------------------------------------------
python3 -c "
import yaml
with open('${SCRIPT_DIR}/action.yml') as f:
    data = yaml.safe_load(f)
outputs = data.get('outputs', {})
expected = ['drift-detected', 'highest-tier', 'report-path']
for out in expected:
    assert out in outputs, f'Missing output: {out}'
" && _ok "action.yml defines expected outputs" || _fail "action.yml missing expected outputs"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "Results: ${PASS} passed, ${FAIL} failed"
if [ "${FAIL}" -gt 0 ]; then
    exit 1
fi
exit 0
