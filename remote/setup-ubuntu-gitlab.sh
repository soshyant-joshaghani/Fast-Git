#!/usr/bin/env bash
# Idempotent GitLab Omnibus + Runner + Docker + UFW setup for Ubuntu/Debian.
#
# Run locally (on the target box):
#   bash remote/setup-ubuntu-gitlab.sh
#   # or: fast-git setup
#
# Or via Fast-Git from a laptop:
#   fast-git provision 192.168.1.50
#
# Env (optional):
#   GITLAB_EXTERNAL_URL   e.g. http://gitlab.example.com  or http://192.168.1.50
#   FAST_GIT_SKIP_RUNNER  set to 1 to skip GitLab Runner install/register
#   GITLAB_RUNNER_TOKEN   registration token (prompted if missing and TTY)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Run as a normal user with sudo — not as root."
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required."
  exit 1
fi

echo "==> Fast-Git: Ubuntu/Debian → GitLab Omnibus + Runner"
echo "    Working dir: $ROOT"
echo

# ── OS check ────────────────────────────────────────────────────────────────
if [[ ! -f /etc/os-release ]]; then
  echo "Unsupported OS (expected Ubuntu/Debian)."
  exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" && "${ID:-}" != "debian" && "${ID_LIKE:-}" != *"debian"* ]]; then
  echo "Warning: tested on Ubuntu/Debian. Continuing on ${PRETTY_NAME:-unknown}..."
fi

CODENAME="${VERSION_CODENAME:-}"
if [[ -z "$CODENAME" ]]; then
  CODENAME="$(lsb_release -cs 2>/dev/null || echo jammy)"
fi

# ── Base packages ───────────────────────────────────────────────────────────
echo "==> Installing base packages..."
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates \
  curl \
  gnupg \
  git \
  openssh-server \
  ufw \
  debian-archive-keyring \
  apt-transport-https

sudo systemctl enable ssh 2>/dev/null || sudo systemctl enable sshd 2>/dev/null || true
sudo systemctl start ssh 2>/dev/null || sudo systemctl start sshd 2>/dev/null || true

# ── Docker ──────────────────────────────────────────────────────────────────
install_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "==> Docker already installed: $(docker --version)"
    docker compose version
    return 0
  fi

  echo "==> Installing Docker Engine + Compose plugin..."
  sudo install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
  fi

  DISTRO_ID="${ID:-ubuntu}"
  if [[ "$DISTRO_ID" != "ubuntu" && "$DISTRO_ID" != "debian" ]]; then
    DISTRO_ID="ubuntu"
  fi

  if [[ ! -f /etc/apt/sources.list.d/docker.list ]]; then
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${DISTRO_ID} ${CODENAME} stable" \
      | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  fi

  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

  sudo systemctl enable docker
  sudo systemctl start docker
}

install_docker

NEED_RELOGIN=0
if ! groups "$USER" | grep -q '\bdocker\b'; then
  echo "==> Adding $USER to the docker group..."
  sudo usermod -aG docker "$USER"
  NEED_RELOGIN=1
fi

docker_cmd() {
  if docker info >/dev/null 2>&1; then
    docker "$@"
  else
    sudo docker "$@"
  fi
}

# ── Firewall ────────────────────────────────────────────────────────────────
echo "==> Configuring UFW..."
sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp comment 'HTTP (GitLab / Traefik)'
sudo ufw allow 443/tcp comment 'HTTPS'
# GitLab SSH clone (often 2222 when 22 is host SSH) — allow both if configured later
sudo ufw allow 2222/tcp comment 'GitLab SSH (optional)' || true
sudo ufw --force enable
echo "    UFW status:"
sudo ufw status numbered

# ── Docker network for Traefik / deployed apps ──────────────────────────────
echo "==> Creating traefik-public network (if missing)..."
if ! docker_cmd network inspect traefik-public >/dev/null 2>&1; then
  docker_cmd network create traefik-public
fi

# ── External URL ────────────────────────────────────────────────────────────
detect_ip() {
  hostname -I 2>/dev/null | awk '{print $1}' || true
}

EXTERNAL_URL="${GITLAB_EXTERNAL_URL:-}"
if [[ -z "$EXTERNAL_URL" ]]; then
  IP="$(detect_ip)"
  if [[ -n "$IP" ]]; then
    EXTERNAL_URL="http://${IP}"
  else
    EXTERNAL_URL="http://127.0.0.1"
  fi
fi
echo "==> GitLab external_url: $EXTERNAL_URL"

# ── GitLab Omnibus ──────────────────────────────────────────────────────────
install_gitlab() {
  if command -v gitlab-ctl >/dev/null 2>&1; then
    echo "==> GitLab already installed: $(gitlab-ctl --version 2>/dev/null || echo present)"
    return 0
  fi

  echo "==> Installing GitLab Omnibus (CE)..."
  curl -fsSL https://packages.gitlab.com/install/repositories/gitlab/gitlab-ce/script.deb.sh \
    | sudo bash

  # EXTERNAL_URL must be set at install time for first-boot config
  sudo EXTERNAL_URL="$EXTERNAL_URL" DEBIAN_FRONTEND=noninteractive apt-get install -y gitlab-ce
}

install_gitlab

# Ensure external_url in gitlab.rb (idempotent reconfigure)
echo "==> Writing /etc/gitlab/gitlab.rb external_url..."
if [[ -f /etc/gitlab/gitlab.rb ]]; then
  if sudo grep -qE '^\s*external_url\s+' /etc/gitlab/gitlab.rb; then
    sudo sed -i.bak -E "s|^[[:space:]]*external_url[[:space:]]+.*|external_url '${EXTERNAL_URL}'|" /etc/gitlab/gitlab.rb
  else
    echo "external_url '${EXTERNAL_URL}'" | sudo tee -a /etc/gitlab/gitlab.rb >/dev/null
  fi
else
  echo "external_url '${EXTERNAL_URL}'" | sudo tee /etc/gitlab/gitlab.rb >/dev/null
fi

echo "==> gitlab-ctl reconfigure (this can take several minutes)..."
sudo gitlab-ctl reconfigure

# ── GitLab Runner ───────────────────────────────────────────────────────────
install_runner() {
  if command -v gitlab-runner >/dev/null 2>&1; then
    echo "==> GitLab Runner already installed: $(gitlab-runner --version | head -n1)"
    return 0
  fi

  echo "==> Installing GitLab Runner..."
  curl -fsSL https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh \
    | sudo bash
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y gitlab-runner

  # Allow runner to use Docker without sudo
  if getent group docker >/dev/null 2>&1; then
    sudo usermod -aG docker gitlab-runner || true
  fi
}

register_runner() {
  if gitlab-runner list 2>/dev/null | grep -qi 'Executor'; then
    echo "==> GitLab Runner already has a registration — skipping register"
    gitlab-runner list || true
    return 0
  fi

  TOKEN="${GITLAB_RUNNER_TOKEN:-}"
  if [[ -z "$TOKEN" ]]; then
    if [[ -t 0 ]]; then
      echo
      echo "Register a runner: GitLab → Admin → CI/CD → Runners → New instance runner"
      echo "(or project Settings → CI/CD → Runners)."
      read -r -p "Runner registration/authentication token (empty to skip): " TOKEN
    else
      echo "==> No TTY and GITLAB_RUNNER_TOKEN unset — skipping runner registration"
      echo "    Later: sudo gitlab-runner register"
      return 0
    fi
  fi

  if [[ -z "$TOKEN" ]]; then
    echo "==> Runner registration skipped"
    return 0
  fi

  echo "==> Registering GitLab Runner (docker executor)..."
  sudo gitlab-runner register \
    --non-interactive \
    --url "$EXTERNAL_URL" \
    --token "$TOKEN" \
    --executor docker \
    --docker-image docker:24 \
    --docker-privileged \
    --docker-volumes /var/run/docker.sock:/var/run/docker.sock \
    --description "fast-git-$(hostname -s)" \
    --tag-list "docker,deploy" \
    || {
      echo "WARNING: gitlab-runner register failed — register manually later"
      return 0
    }
}

if [[ "${FAST_GIT_SKIP_RUNNER:-0}" != "1" ]]; then
  install_runner
  register_runner
else
  echo "==> Skipping GitLab Runner (FAST_GIT_SKIP_RUNNER=1)"
fi

# ── Summary ─────────────────────────────────────────────────────────────────
ROOT_PW_FILE="/etc/gitlab/initial_root_password"
echo
echo "============================================"
echo " Fast-Git setup complete"
echo "============================================"
echo
echo " GitLab URL:     $EXTERNAL_URL"
echo " SSH (host):     $(whoami)@$(detect_ip || hostname)"
if [[ -f "$ROOT_PW_FILE" ]]; then
  echo " Root password:  sudo cat $ROOT_PW_FILE"
  echo "                 (file deleted 24h after first reconfigure)"
else
  echo " Root password:  (initial_root_password already rotated/removed)"
fi
echo
echo " Next:"
echo "   1. Open $EXTERNAL_URL and sign in as root"
echo "   2. Create a PAT → save as safe/gitlab.token on your laptop"
echo "   3. Seed projects:  fast-git project seed ./Fast-Svelte --profile fast-family"
echo
if command -v gitlab-runner >/dev/null 2>&1; then
  echo " Runner:"
  gitlab-runner status 2>/dev/null || sudo gitlab-runner status 2>/dev/null || true
  gitlab-runner list 2>/dev/null || true
fi
echo

if [[ "$NEED_RELOGIN" -eq 1 ]]; then
  echo "NOTE: Log out and back in (or run 'newgrp docker') so docker runs without sudo."
  echo
fi
