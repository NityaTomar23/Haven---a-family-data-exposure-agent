"""The hackathon's pass/fail constraints, as executable checks.

These are the claims a judge can verify without trusting the authors:

* all inference goes to Nebius Token Factory, and never to
  integrate.api.nvidia.com or build.nvidia.com;
* at least one NVIDIA open-source model, arranged as a graded tier ladder;
* the only outbound paths in shipped code are the two sanctioned SDKs;
* the repository is honest about what has not been verified.

The last one matters most. A README that implies a proof that was never run is
worse than a README that admits the gap.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from haven import llm

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_HOSTS = ("integrate.api.nvidia.com", "build.nvidia.com")

# llm.py is allowed to name the forbidden hosts, because it holds the denylist
# constant. Everywhere else is a violation.
FILES_ALLOWED_TO_NAME_FORBIDDEN_HOSTS = {Path("src/haven/llm.py")}


def shipped_python_files() -> list[Path]:
    files: list[Path] = []
    for root in ("src", "scripts"):
        files.extend(sorted((REPO_ROOT / root).rglob("*.py")))
    return [path for path in files if "__pycache__" not in path.parts]


def shipped_text_files() -> list[Path]:
    """Code and configuration only -- the things that can actually route traffic.

    Prose is excluded on purpose: a README that *warns* about the forbidden
    endpoints is desirable, not a violation. That the docs do warn is asserted
    separately by test_the_docs_warn_about_the_forbidden_endpoints.
    """
    files = shipped_python_files() + [
        REPO_ROOT / ".env.example",
        *sorted((REPO_ROOT / "policy").glob("*.yaml")),
        *sorted((REPO_ROOT / "agent").glob("*.example")),
    ]
    return [path for path in files if path.exists()]


def markdown_docs() -> list[Path]:
    docs = [REPO_ROOT / "README.md"]
    for directory in ("agent", "docs", "policy"):
        docs.extend(sorted((REPO_ROOT / directory).glob("*.md")))
    return [path for path in docs if path.exists()]


def without_comments(text: str) -> str:
    """Drop comment lines.

    A forbidden host may legitimately appear in a *warning* ("NVIDIA_BASE_URL
    defaults to ... and must never be used"), and that warning is valuable. What
    must never appear is the host in a live setting, so comment lines -- `#` in
    Python, YAML, shell and dotenv -- are excluded before searching.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


# ── One sanctioned inference endpoint ──────────────────────────────────


def test_no_forbidden_inference_host_in_shipped_code():
    offenders = []
    for path in shipped_text_files():
        text = without_comments(path.read_text(encoding="utf-8", errors="replace"))
        for host in FORBIDDEN_HOSTS:
            if host in text and path.relative_to(REPO_ROOT) not in FILES_ALLOWED_TO_NAME_FORBIDDEN_HOSTS:
                offenders.append(f"{path.relative_to(REPO_ROOT)} names {host}")

    assert not offenders, (
        "inference must not route to the NVIDIA-hosted endpoints: " + "; ".join(offenders)
    )


def test_llm_module_only_names_the_forbidden_hosts_in_its_denylist():
    """llm.py may name them, but only as the denylist constant -- never as a
    value that could be used as an endpoint."""
    assert set(llm.FORBIDDEN_INFERENCE_HOSTS) == set(FORBIDDEN_HOSTS)

    tree = ast.parse(Path(llm.__file__).read_text(encoding="utf-8"))

    declared: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "FORBIDDEN_INFERENCE_HOSTS"
            for target in node.targets
        ):
            declared = {
                element.value
                for element in node.value.elts
                if isinstance(element, ast.Constant)
            }
    assert declared == set(FORBIDDEN_HOSTS)

    mentioned = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in FORBIDDEN_HOSTS
    }
    assert mentioned <= declared, f"named outside the denylist: {mentioned - declared}"


def test_the_docs_warn_about_the_forbidden_endpoints():
    """The warning must exist somewhere in the prose, so deleting it fails."""
    prose = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in markdown_docs()
    )

    for host in FORBIDDEN_HOSTS:
        assert host in prose, f"no documentation warns about {host}"


def test_default_endpoint_is_token_factory():
    assert "tokenfactory" in llm.TOKEN_FACTORY_BASE_URL
    assert llm.TOKEN_FACTORY_BASE_URL == llm.base_url()


def test_every_permitted_endpoint_is_token_factory():
    assert llm.ALLOWED_TOKEN_FACTORY_BASE_URLS
    for url in llm.ALLOWED_TOKEN_FACTORY_BASE_URLS:
        assert "tokenfactory" in url, url


def test_base_url_is_overridable(monkeypatch):
    """The brief mandates the regional host; Nebius documents it as liable to
    stop working, so switching must be a configuration change."""
    monkeypatch.setenv("NEBIUS_BASE_URL", llm.DOCUMENTED_GLOBAL_BASE_URL)
    assert llm.base_url() == llm.DOCUMENTED_GLOBAL_BASE_URL

    monkeypatch.delenv("NEBIUS_BASE_URL")
    assert llm.base_url() == llm.SPEC_REGIONAL_BASE_URL


# ── Tiered NVIDIA open models ──────────────────────────────────────────


def test_three_tiers_are_configured():
    assert set(llm.TIER_MODELS) == {"nano", "super", "ultra"}


def test_every_tier_is_an_nvidia_model():
    for tier, model in llm.TIER_MODELS.items():
        assert model.startswith("nvidia/"), f"{tier} is not an NVIDIA model: {model}"


def test_tiers_use_distinct_models():
    """A tier ladder that maps every tier to one model is not tiering."""
    assert len(set(llm.TIER_MODELS.values())) == 3


def test_super_and_ultra_ids_match_the_official_cookbook():
    """Verified against nebius/token-factory-cookbook models/nemotron/README.md.
    The nano id is NOT verified and is deliberately not asserted here."""
    assert llm.TIER_MODELS["super"] == "nvidia/nemotron-3-super-120b-a12b"
    assert llm.TIER_MODELS["ultra"] == "nvidia/Nemotron-3-Ultra-550b-a55b"


def test_nano_tier_is_documented_as_unverified():
    """If someone verifies it, they must also update this test and the docs."""
    source = Path(llm.__file__).read_text(encoding="utf-8")
    assert "UNVERIFIED" in source
    assert "nano" in source


def test_model_ids_are_overridable(monkeypatch):
    monkeypatch.setenv("NEBIUS_MODEL_NANO", "nvidia/Nemotron-3_5-Lightning")
    assert llm.model_for("nano") == "nvidia/Nemotron-3_5-Lightning"

    monkeypatch.delenv("NEBIUS_MODEL_NANO")
    assert llm.model_for("nano") == llm.TIER_MODELS["nano"]


def test_model_for_covers_every_tier():
    for tier in ("nano", "super", "ultra"):
        assert llm.model_for(tier)


def test_verify_models_helper_exists():
    """The only way to settle the nano id is a live /v1/models call."""
    assert callable(llm.verify_models)


# ── No unsanctioned outbound paths ─────────────────────────────────────


@pytest.mark.parametrize(
    "module",
    [
        "api",
        "evidence",
        "fixtures",
        "llm",
        "models",
        "offline",
        "pipeline",
        "privacy",
        "research",
        "seed",
    ],
)
def test_modules_do_not_import_generic_http_clients(module: str):
    """Shipped code may only reach the network through the Tavily and OpenAI
    SDKs. A raw HTTP client is how an automated submission would sneak in."""
    source = (REPO_ROOT / "src" / "haven" / f"{module}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    forbidden = {"requests", "httpx", "aiohttp", "urllib", "smtplib", "selenium", "playwright"}
    assert not (imported & forbidden), (
        f"haven.{module} imports {sorted(imported & forbidden)}"
    )


def test_only_the_two_sanctioned_sdks_are_used_for_network_io():
    """research.py talks to Tavily, llm.py talks to Token Factory."""
    research = (REPO_ROOT / "src" / "haven" / "research.py").read_text(encoding="utf-8")
    llm_source = Path(llm.__file__).read_text(encoding="utf-8")

    assert "from tavily import TavilyClient" in research
    assert "from openai import OpenAI" in llm_source


# ── Honesty guards ─────────────────────────────────────────────────────


def test_readme_discloses_the_unverified_sandbox_status():
    """The sandbox boundary has never been executed on this host. Any README
    that omits that is overstating the project's central claim."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()

    assert "unverified" in readme or "not been verified" in readme or "not yet verified" in readme
    assert "openshell" in readme


def test_policy_readme_discloses_that_the_policy_was_never_loaded():
    readme = (REPO_ROOT / "policy" / "README.md").read_text(encoding="utf-8")

    assert "NOT verified" in readme or "not been loaded" in readme


def test_licence_file_exists():
    """The hackathon requires an OSI licence visible in the GitHub About box."""
    licence = REPO_ROOT / "LICENSE"
    assert licence.exists()
    assert "MIT License" in licence.read_text(encoding="utf-8")
