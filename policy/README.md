# Haven policy artifacts

## Status: authored, NOT verified

Every file in this directory is written against NVIDIA's published OpenShell
documentation and **none of it has been loaded by OpenShell**. OpenShell
requires Linux with Landlock ABI v3 (Linux 6.2+) and Docker 28.0+. This
checkout was prepared on Windows 11 with neither WSL nor Docker installed.

Do not describe the boundary as proven until `boundary_test.sh` has run on
Linux and its output is committed under `docs/`.

## The files

| File | Role |
| --- | --- |
| `policy.yaml` | The **provable core**: filesystem, process, Landlock and REST network rules. Deny-by-default. |
| `policy.hardened.yaml` | `policy.yaml` plus an enforcement-layer regex middleware that redacts high-sensitivity patterns from allowed request bodies, fail-closed. |
| `boundary.yaml` | The boundary policy for the prover: the most access Haven may ever have. |
| `counterexample.yaml` | `policy.yaml` plus one host the boundary forbids. Exists to prove the prover discriminates. |
| `boundary_test.sh` | The four-step boundary test. |

## Why two policy files

The regex middleware is the strongest exfiltration control in this project:
it strips sensitive patterns at the proxy boundary, in the enforcement layer,
failing closed. That is a categorically stronger claim than "the agent was
instructed not to send them."

But the Policy Prover models five domains — filesystem, process, Landlock,
network connections (L4), and REST requests. `network_middlewares` is not one
of them, and the prover returns `unsupported` for rules it cannot model rather
than ignoring them. Since **only `within_boundary` counts as a pass**, adding
the middleware may make the policy unprovable even though it is strictly more
restrictive.

So the honest arrangement is:

* **run** `policy.hardened.yaml` in the sandbox, and
* **prove** `policy.yaml` against `boundary.yaml`.

Report both facts. Never present the middleware as prover-verified.

## Running the proof

```bash
# Install OpenShell (Linux or macOS arm64; Windows needs WSL 2 + Docker Desktop)
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh | sh

openshell gateway add http://127.0.0.1:18080 --local --name local
openshell gateway select local

openshell sandbox create --name haven \
  --policy policy/policy.hardened.yaml -- /bin/bash

policy/boundary_test.sh haven
```

The test writes `docs/policy-prover-policy.json` and
`docs/policy-prover-counterexample.json` — commit both as evidence.

## Two deviations from the original design sketch, both deliberate

1. **`landlock.compatibility: hard_requirement`, not `best_effort`.** OpenShell
   documents that `best_effort` "runs without the filesystem rules and logs a
   high-severity finding" when the rules cannot be applied. That would silently
   void half the policy. The prover agrees: it reports `exceeds_boundary` when
   a candidate downgrades `hard_requirement` to `best_effort`.

2. **Real interpreter paths in `binaries`.** OpenShell matches the executable's
   resolved path and hashes it, and warns against listing a symlink. `/usr/bin/python3`
   is normally a symlink to `python3.12`. Confirm on the target image:

   ```bash
   readlink -f "$(command -v python3)"
   ```

## Unverified details to check on the target host

* The `openshell/regex` middleware's pattern configuration. The reference
  documents `mode: redact` but not the pattern keys, so no pattern list is
  invented here. If the installed version rejects the block, remove it.
* `/usr/local/bin/hermes` as the agent binary path, which comes from the
  design sketch rather than from an installed image.
* Whether OpenShell accepts two exact Token Factory hosts on port 443 in one
  policy. Both are listed because Nebius documents the regional base URL as
  liable to stop working; if the prover returns `unsupported`, drop the
  regional host and switch `NEBIUS_BASE_URL` to the documented global host.
