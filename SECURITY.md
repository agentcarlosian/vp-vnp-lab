# Security Policy

## Scope

`vp-vnp-lab` contains research formalizations and engineering verification tools (`pcvh`, `lean-orch`, `qcat0`).
For untrusted candidate proof packages, use the isolated Docker verification workflow (`pcvh verify`) rather than `--trusted-local`.

## Reporting a Vulnerability

Please do not disclose exploitable vulnerabilities in public issues.

1. Use GitHub's private vulnerability reporting feature on this repository if available.
2. Otherwise contact the maintainer at `carlosian@agentmail.to`.

Include the affected component, commit SHA, minimal reproduction steps, and the trust boundary crossed. Never attach private signing keys or third-party credentials.
