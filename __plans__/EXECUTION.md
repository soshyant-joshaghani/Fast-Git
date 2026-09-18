# Fast-Git execution plan

**Live status:** [PROGRESS.md](./PROGRESS.md)  
**Product contract:** [README.md](../README.md)

## Goal

Standalone CLI that turns any Ubuntu/Debian machine into a GitLab Omnibus + Runner node and seeds Fast-* projects with CI/CD — generalizing Fast-Svelte `__ctrl__` patterns.

## Critical path

```text
S0 scaffold (entrypoints, lib, servers.json)
→ S1 remote/setup-ubuntu-gitlab.sh (Docker + UFW + Omnibus + Runner)
→ S2 fast-git setup / status / gitlab / runner
→ S3 gitlab_api + project create/list/remove
→ S4 project seed (generic → fast-family / python / docker)
→ S5 provision <host> (SSH dispatch)
```

## Stage details

### S0 — Scaffold

- Mirror Fast-Svelte `__ctrl__`: `main.py`, `.bat`/`.sh`, `lib/`, `safe/`, `servers.json`.
- Lift `ssh.py` / `keys.py` / dispatch summary (`ok=/offline=/failed=`).

### S1 — Install script

- Idempotent bash: base packages, Docker (official apt), UFW, `traefik-public`, GitLab CE Omnibus, Runner.
- Safe to re-run; skip steps when already present.

### S2 — Local ops

- `setup` runs S1 on this machine (Linux/WSL); Windows users use `provision`.
- `status` / `gitlab *` / `runner *`.

### S3 — API

- `lib/gitlab_api.py` via REST + `safe/gitlab.token`.
- `project create|list|remove`.

### S4 — Seed

- Create project, optional `.gitlab-ci.yml` from profile, `git remote` + push.
- `fast-family` wires each project's own `__ctrl__` scripts.

### S5 — Provision

- Upload + run setup script over SSH; multi-target via `servers.json`.

## Explicit non-goals

- GitLab-in-Docker
- Replacing per-project `__ctrl__/remote` deploy to app VMs
- Windows-native Omnibus install (use WSL or remote Ubuntu)
