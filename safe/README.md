# safe/

Local secrets for Fast-Git. **Never commit** PEM keys, tokens, or address files.

| File | Purpose |
|------|---------|
| `*.pem` / `*.key` | SSH private keys for `fast-git provision` |
| `*-address.txt` | Optional host IP/hostname (one line) |
| `gitlab.token` | Personal access token / root token for GitLab API |
| `*.env` | Optional env snippets |

Copy examples:

```bash
cp safe/gitlab.token.example safe/gitlab.token
# edit and paste your GitLab API token
```

Token needs scopes: `api`, `read_repository`, `write_repository` (or a root token on a fresh Omnibus install).
