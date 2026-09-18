#!/bin/bash
# macOS double-click entry → same CLI as fast-git.sh
# Args are forwarded, e.g. open Terminal and run:
#   ./fast-git.command
#   ./fast-git.command setup-local
#   ./fast-git.command setup
#   ./fast-git.command status
#   ./fast-git.command ping all
#   ./fast-git.command project seed ../fast-template/fast-svelte --profile fast-family
#   ./fast-git.command provision 192.168.1.50 --key safe/vm.pem
#   ./fast-git.command flatten --yes
#   ./fast-git.command restore-flat --yes
# If you see: env: bash\r: No such file or directory
#   sed -i '' 's/\r$//' "$0" && chmod +x "$0" && exec "$0" "$@"
# Then re-open, or run: bash "$(dirname "$0")/fast-git.sh"

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Heal CRLF if this file was checked out / copied from Windows
if grep -q $'\r' "$0" 2>/dev/null; then
  echo "[fast-git] Fixing Windows line endings in $(basename "$0")..."
  tmp="$(mktemp)"
  tr -d '\r' <"$0" >"$tmp"
  chmod +x "$tmp"
  # Replace in place (same inode path for Finder re-runs)
  cat "$tmp" >"$0"
  rm -f "$tmp"
  exec /bin/bash "$0" "$@"
fi

chmod +x "$DIR/fast-git.sh" 2>/dev/null || true
exec /bin/bash "$DIR/fast-git.sh" "$@"
