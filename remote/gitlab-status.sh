#!/usr/bin/env bash
# Print health of GitLab Omnibus, Runner, Docker, and UFW on this machine.
set -euo pipefail

echo "==> Fast-Git status"
echo

ok() { echo "[ok] $*"; }
bad() { echo "[!] $*"; }

# Docker
if command -v docker >/dev/null 2>&1; then
  ok "Docker: $(docker --version 2>/dev/null | head -n1)"
  if docker compose version >/dev/null 2>&1; then
    ok "Compose: $(docker compose version 2>/dev/null | head -n1)"
  else
    bad "Docker Compose plugin missing"
  fi
  if docker network inspect traefik-public >/dev/null 2>&1; then
    ok "Network: traefik-public"
  else
    bad "Network: traefik-public missing"
  fi
else
  bad "Docker not installed"
fi

echo

# GitLab
if command -v gitlab-ctl >/dev/null 2>&1; then
  ok "gitlab-ctl present"
  echo "---- gitlab-ctl status ----"
  sudo gitlab-ctl status || true
  echo "---------------------------"
  if [[ -f /etc/gitlab/gitlab.rb ]]; then
    ext="$(sudo grep -E '^\s*external_url' /etc/gitlab/gitlab.rb | head -n1 || true)"
    [[ -n "$ext" ]] && ok "Config: $ext"
  fi
  if [[ -f /etc/gitlab/initial_root_password ]]; then
    ok "Initial root password file still present (/etc/gitlab/initial_root_password)"
  fi
else
  bad "GitLab Omnibus not installed"
fi

echo

# Runner
if command -v gitlab-runner >/dev/null 2>&1; then
  ok "gitlab-runner: $(gitlab-runner --version 2>/dev/null | head -n1)"
  gitlab-runner status 2>/dev/null || sudo gitlab-runner status 2>/dev/null || bad "Runner service not running"
  echo "---- gitlab-runner list ----"
  gitlab-runner list 2>/dev/null || true
  echo "----------------------------"
else
  bad "GitLab Runner not installed"
fi

echo

# UFW
if command -v ufw >/dev/null 2>&1; then
  echo "---- ufw status ----"
  sudo ufw status numbered || true
  echo "-------------------"
else
  bad "ufw not installed"
fi
