"""Static validation of the OpenShell policy artifacts.

These tests cannot prove the egress boundary -- only OpenShell on Linux can do
that, and it has not been run. What they *can* do is catch the mistakes that
would make the eventual proof meaningless, all of which are silent failures in
OpenShell itself:

* a symlinked interpreter path, which never matches the hashed executable;
* filesystem paths that differ between candidate and boundary, which makes the
  prover return `unsupported` instead of comparing them;
* a counterexample that is not actually over-broad, which would make the
  "prover discriminates" step pass for the wrong reason;
* `landlock: best_effort` creeping back in, which silently voids the
  filesystem policy;
* `enforcement: audit`, which logs violations and allows them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = REPO_ROOT / "policy"

POLICY = POLICY_DIR / "policy.yaml"
HARDENED = POLICY_DIR / "policy.hardened.yaml"
BOUNDARY = POLICY_DIR / "boundary.yaml"
COUNTEREXAMPLE = POLICY_DIR / "counterexample.yaml"

ALL_POLICIES = [POLICY, HARDENED, BOUNDARY, COUNTEREXAMPLE]

TOKEN_FACTORY_REGIONAL = "api.tokenfactory.us-central1.nebius.com"
TOKEN_FACTORY_GLOBAL = "api.tokenfactory.nebius.com"
TAVILY_HOST = "api.tavily.com"


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def allow_matchers(policy: dict) -> set[tuple[str, int, str, str]]:
    """Flatten a policy into (host, port, method, path) allow matchers."""
    matchers: set[tuple[str, int, str, str]] = set()
    for rule in (policy.get("network_policies") or {}).values():
        for endpoint in rule.get("endpoints") or []:
            for entry in endpoint.get("rules") or []:
                matcher = entry["allow"]
                matchers.add(
                    (
                        endpoint["host"],
                        endpoint["port"],
                        matcher["method"],
                        matcher["path"],
                    )
                )
    return matchers


def binary_paths(policy: dict) -> set[str]:
    paths: set[str] = set()
    for rule in (policy.get("network_policies") or {}).values():
        for binary in rule.get("binaries") or []:
            paths.add(binary["path"])
    return paths


def endpoints(policy: dict) -> list[dict]:
    found = []
    for rule in (policy.get("network_policies") or {}).values():
        found.extend(rule.get("endpoints") or [])
    return found


# ── Every policy file ──────────────────────────────────────────────────


@pytest.mark.parametrize("path", ALL_POLICIES, ids=lambda p: p.name)
def test_policy_file_exists_and_is_valid_yaml(path: Path):
    assert path.exists(), f"{path.name} is missing"
    assert isinstance(load(path), dict)


@pytest.mark.parametrize("path", ALL_POLICIES, ids=lambda p: p.name)
def test_schema_version_is_one(path: Path):
    assert load(path)["version"] == 1


@pytest.mark.parametrize("path", ALL_POLICIES, ids=lambda p: p.name)
def test_landlock_is_a_hard_requirement(path: Path):
    """best_effort silently runs without the filesystem rules; the prover
    reports exceeds_boundary when a candidate downgrades to it."""
    assert load(path)["landlock"]["compatibility"] == "hard_requirement"


@pytest.mark.parametrize("path", ALL_POLICIES, ids=lambda p: p.name)
def test_workload_runs_as_the_sandbox_user(path: Path):
    process = load(path)["process"]
    assert process["run_as_user"] == "sandbox"
    assert process["run_as_group"] == "sandbox"


@pytest.mark.parametrize("path", ALL_POLICIES, ids=lambda p: p.name)
def test_every_endpoint_is_enforced_not_audited(path: Path):
    """audit logs violations and allows the request, and the prover refuses to
    model it."""
    for endpoint in endpoints(load(path)):
        assert endpoint["enforcement"] == "enforce", (
            f"{path.name}: {endpoint['host']} uses "
            f"enforcement={endpoint['enforcement']!r}"
        )


@pytest.mark.parametrize("path", ALL_POLICIES, ids=lambda p: p.name)
def test_root_is_never_writable(path: Path):
    """read_write may not contain '/', and a writable root voids the policy."""
    assert "/" not in load(path)["filesystem_policy"]["read_write"]


@pytest.mark.parametrize("path", ALL_POLICIES, ids=lambda p: p.name)
def test_binaries_are_real_paths_not_symlinks(path: Path):
    """OpenShell matches the resolved executable, so /usr/bin/python3 (a
    symlink on Debian and Ubuntu) would never match."""
    for binary in binary_paths(load(path)):
        assert binary != "/usr/bin/python3", (
            f"{path.name}: list the resolved interpreter, e.g. /usr/bin/python3.12"
        )


@pytest.mark.parametrize("path", ALL_POLICIES, ids=lambda p: p.name)
def test_no_other_host_is_reachable(path: Path):
    """Deny-by-default only holds if the allowlist is exactly these hosts."""
    hosts = {endpoint["host"] for endpoint in endpoints(load(path))}
    assert hosts <= {TOKEN_FACTORY_REGIONAL, TOKEN_FACTORY_GLOBAL, TAVILY_HOST, "example.com"}


# ── The candidate and its boundary ─────────────────────────────────────


def test_both_token_factory_hosts_are_allowlisted():
    """The regional host is mandated by the brief; the global host is the
    documented fallback if the region moves."""
    hosts = {endpoint["host"] for endpoint in endpoints(load(POLICY))}
    assert TOKEN_FACTORY_REGIONAL in hosts
    assert TOKEN_FACTORY_GLOBAL in hosts


def test_tavily_is_restricted_to_search_and_extract():
    matchers = {m for m in allow_matchers(load(POLICY)) if m[0] == TAVILY_HOST}
    assert matchers == {
        (TAVILY_HOST, 443, "POST", "/search"),
        (TAVILY_HOST, 443, "POST", "/extract"),
    }


def test_candidate_filesystem_paths_match_the_boundary():
    """The prover compares paths one by one; different paths return unsupported."""
    candidate = load(POLICY)["filesystem_policy"]
    boundary = load(BOUNDARY)["filesystem_policy"]
    assert candidate["read_only"] == boundary["read_only"]
    assert candidate["read_write"] == boundary["read_write"]
    assert candidate["include_workdir"] == boundary["include_workdir"]


def test_candidate_is_within_the_boundary():
    """The step-3 proof is only meaningful if this holds structurally."""
    candidate = allow_matchers(load(POLICY))
    boundary = allow_matchers(load(BOUNDARY))
    assert candidate <= boundary, f"outside the boundary: {candidate - boundary}"


def test_candidate_binaries_are_within_the_boundary():
    assert binary_paths(load(POLICY)) <= binary_paths(load(BOUNDARY))


def test_counterexample_actually_exceeds_the_boundary():
    """Otherwise the 'the prover discriminates' step passes vacuously."""
    counter = allow_matchers(load(COUNTEREXAMPLE))
    boundary = allow_matchers(load(BOUNDARY))
    assert counter - boundary, "counterexample adds nothing outside the boundary"


def test_counterexample_plants_exactly_one_extra_host():
    counter_hosts = {endpoint["host"] for endpoint in endpoints(load(COUNTEREXAMPLE))}
    boundary_hosts = {endpoint["host"] for endpoint in endpoints(load(BOUNDARY))}
    assert counter_hosts - boundary_hosts == {"example.com"}


# ── The provable core vs the hardened variant ──────────────────────────


def test_provable_core_has_no_middleware():
    """The prover does not model network_middlewares and returns unsupported
    for rules it cannot model -- which counts as a failure."""
    assert "network_middlewares" not in load(POLICY)


def test_hardened_variant_adds_a_fail_closed_redactor():
    middlewares = load(HARDENED)["network_middlewares"]
    redactor = middlewares["redact-high-sensitivity"]

    assert redactor["middleware"] == "openshell/regex"
    assert redactor["config"]["mode"] == "redact"
    assert redactor["on_error"] == "fail_closed", (
        "fail_open would forward an unredacted body when the filter fails"
    )


def test_hardened_variant_is_otherwise_identical_to_the_core():
    """The only difference must be the middleware, or the two files drift."""
    hardened = load(HARDENED)
    core = load(POLICY)

    assert hardened["filesystem_policy"] == core["filesystem_policy"]
    assert hardened["landlock"] == core["landlock"]
    assert hardened["process"] == core["process"]
    assert allow_matchers(hardened) == allow_matchers(core)


def test_redactor_covers_every_allowed_host():
    redactor = load(HARDENED)["network_middlewares"]["redact-high-sensitivity"]
    covered = set(redactor["endpoints"]["include"])
    assert covered == {TOKEN_FACTORY_REGIONAL, TOKEN_FACTORY_GLOBAL, TAVILY_HOST}


# ── Housekeeping ───────────────────────────────────────────────────────


def test_boundary_test_script_is_executable_and_guards_the_positive_control():
    """A boundary test without a positive control passes on a dead network."""
    script = (POLICY_DIR / "boundary_test.sh").read_text(encoding="utf-8")

    assert "positive control" in script.lower()
    assert "within_boundary" in script
    assert "exceeds_boundary" in script
    assert "BOUNDARY NOT PROVEN" in script


def test_boundary_test_does_not_use_a_non_allowlisted_binary():
    """Probing with curl would fail because curl is not allowlisted, not
    because the host is denied -- the test would pass for the wrong reason."""
    script = (POLICY_DIR / "boundary_test.sh").read_text(encoding="utf-8")

    assert "python3 -c" in script
    assert "curl" not in script
