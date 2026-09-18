# Fast-Git progress

Last updated: 2026-09-18

| Stage | Status | Notes |
|-------|--------|-------|
| S0 scaffold | **done** | `main.py`, entrypoints, `lib/`, `profiles/`, `servers.json`, `safe/` |
| S1 setup script | **done** | `remote/setup-ubuntu-gitlab.sh` (+ status/backup) |
| S2 local ops | **done** | `setup`, `status`, `gitlab *`, `runner *` |
| S3 API | **done** | `lib/gitlab_api.py` + project create/list/remove |
| S4 seed | **done** | generic / fast-family / python / docker profiles |
| S5 provision | **done** | SSH upload + run; `servers.json` multi-target |

## Smoke checklist (manual)

- [ ] On Ubuntu VM: `./fast-git.sh setup` completes; GitLab UI reachable
- [ ] `./fast-git.sh status` shows gitlab-ctl + runner + docker
- [ ] Token in `safe/gitlab.token`; `project list` works
- [ ] `project seed <fast-svelte> --profile fast-family` pushes + writes CI
- [ ] From laptop: `fast-git.bat provision <ip> --key safe/….pem`
