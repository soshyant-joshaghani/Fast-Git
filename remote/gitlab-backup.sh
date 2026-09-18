#!/usr/bin/env bash
# Create a GitLab Omnibus backup (config + repositories + DB).
# See: https://docs.gitlab.com/ee/administration/backup_restore/
set -euo pipefail

if ! command -v gitlab-backup >/dev/null 2>&1 && ! command -v gitlab-ctl >/dev/null 2>&1; then
  echo "GitLab Omnibus not installed."
  exit 1
fi

echo "==> Creating GitLab backup (this may take a while)..."
sudo gitlab-backup create STRATEGY=copy
echo
echo "==> Backing up /etc/gitlab (secrets + gitlab.rb)..."
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="${FAST_GIT_BACKUP_DIR:-$HOME/fast-git-backups}"
mkdir -p "$OUT_DIR"
sudo tar -czf "$OUT_DIR/gitlab-etc-${STAMP}.tar.gz" -C / etc/gitlab
sudo chown "$USER:$USER" "$OUT_DIR/gitlab-etc-${STAMP}.tar.gz" 2>/dev/null || true

echo
echo "Done."
echo "  Omnibus dump: /var/opt/gitlab/backups/"
echo "  Config tarball: $OUT_DIR/gitlab-etc-${STAMP}.tar.gz"
echo
echo "Keep gitlab-secrets.json with the backup — restore needs it."
