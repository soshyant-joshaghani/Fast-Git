#!/usr/bin/env python3
"""Fast-Git — turn this machine (or a remote VM) into a GitLab + Runner node.

Sibling CLI to Fast-Svelte's __ctrl__: argparse + lib/* + remote/*.sh.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.actions import run_raw
from lib.config import (
    REMOTE_DIR,
    gitlab_url,
    list_servers,
    require_host,
    resolve_targets,
    server_from_host,
)
from lib.gitlab_api import GitLabAPI
from lib.keys import resolve_ssh_key
from lib.ops import (
    local_backup,
    local_quick_status,
    local_setup,
    local_status,
    provision_remote,
    remote_status,
    run_local_script,
)
from lib.seed import seed_project
from lib.ssh import (
    close_log,
    echo,
    print_result,
    run_command,
    run_parallel,
    save_results_json,
    with_retries,
)
from utils.gitflat.cli import build_flatten_subparser, build_restore_flat_subparser
from utils.local.cli import build_setup_local_subparser


def _dispatch(targets: list[dict], worker, *, parallel: bool = True) -> int:
    start = time.time()
    if parallel and len(targets) > 1:
        results = run_parallel(targets, worker)
    else:
        results = [
            with_retries(s, lambda client, _s=s: worker(client, _s)) for s in targets
        ]

    for r in results:
        print_result(r)

    ok = sum(1 for r in results if r["status"] == "success")
    offline = sum(1 for r in results if r["status"] == "offline")
    failed = len(results) - ok - offline
    path = save_results_json(results)
    echo(
        f"\nsummary: ok={ok} offline={offline} failed={failed}  ({time.time() - start:.1f}s)"
    )
    echo(f"results: {path}")
    close_log()
    return 0 if failed == 0 and offline == 0 else 1


def cmd_list(_: argparse.Namespace) -> int:
    servers = list_servers(include_disabled=True)
    print(f"{'ID':<18} {'HOST':<22} ON")
    print("-" * 50)
    for s in servers:
        on = "yes" if s.get("enabled", True) is not False else "no"
        host = s.get("host") or "(empty)"
        print(f"{s['id']:<18} {host:<22} {on}")
    return 0


def _add_target(p: argparse.ArgumentParser, *, default: str = "all") -> None:
    p.add_argument(
        "target",
        nargs="?",
        default=default,
        help="server id (or 'all')",
    )
    p.add_argument(
        "--all-disabled",
        action="store_true",
        help="include servers with enabled=false",
    )


def cmd_ping(args: argparse.Namespace) -> int:
    targets = resolve_targets(args.target, include_disabled=args.all_disabled)

    def worker(client, server):
        _ = server
        code, out, err = run_command(client, "hostname && uname -a", timeout=30)
        return {
            "status": "success" if code == 0 else "failed",
            "output": (out or err).strip(),
        }

    return _dispatch(targets, worker, parallel=True)


def cmd_connect(args: argparse.Namespace) -> int:
    targets = resolve_targets(args.target, include_disabled=args.all_disabled)
    if len(targets) != 1:
        raise SystemExit("connect requires exactly one server id (not all)")
    server = targets[0]
    host = require_host(server)
    try:
        key = resolve_ssh_key(server["key"])
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from exc
    user = server.get("user", "ubuntu")
    port = int(server.get("port", 22))
    echo(f"ssh -i {key} -p {port} {user}@{host}")
    return subprocess.call(
        ["ssh", "-i", key, "-p", str(port), f"{user}@{host}"]
    )


def cmd_exec(args: argparse.Namespace) -> int:
    targets = resolve_targets(args.target)

    def worker(client, server):
        return run_raw(
            client,
            server,
            args.cmd,
            in_project=args.in_project,
            timeout=args.timeout,
        )

    return _dispatch(targets, worker, parallel=args.parallel)


def cmd_setup(args: argparse.Namespace) -> int:
    return local_setup(
        skip_runner=bool(args.skip_runner),
        external_url=args.external_url,
    )


def cmd_status(_: argparse.Namespace) -> int:
    try:
        return local_status()
    except SystemExit as exc:
        # Non-Linux: fall back to quick checks
        msg = str(exc)
        if "Linux" in msg or "WSL" in msg:
            echo(msg)
            echo("")
            return local_quick_status()
        raise


def cmd_gitlab_install(args: argparse.Namespace) -> int:
    return local_setup(
        skip_runner=True,
        external_url=args.external_url,
    )


def cmd_gitlab_status(_: argparse.Namespace) -> int:
    return run_local_script(REMOTE_DIR / "gitlab-status.sh")


def cmd_gitlab_restart(_: argparse.Namespace) -> int:
    return subprocess.call(["sudo", "gitlab-ctl", "restart"])


def cmd_gitlab_backup(_: argparse.Namespace) -> int:
    return local_backup()


def cmd_runner_install(_: argparse.Namespace) -> int:
    script = REMOTE_DIR / "setup-ubuntu-gitlab.sh"
    # Re-run setup but only the runner pieces are non-idempotent skip for gitlab —
    # simplest path: run full setup with env that still installs runner.
    echo("==> Re-running setup script (idempotent; ensures Runner package)")
    return local_setup(skip_runner=False)


def cmd_runner_register(args: argparse.Namespace) -> int:
    import os

    env = os.environ.copy()
    if args.token:
        env["GITLAB_RUNNER_TOKEN"] = args.token
    if args.url:
        env["GITLAB_EXTERNAL_URL"] = args.url
    else:
        env.setdefault("GITLAB_EXTERNAL_URL", gitlab_url())
    # Invoke register via a small inline bash if runner exists
    if subprocess.call(["bash", "-c", "command -v gitlab-runner"]) != 0:
        raise SystemExit("gitlab-runner not installed — run: fast-git runner install")
    token = env.get("GITLAB_RUNNER_TOKEN") or args.token
    if not token:
        raise SystemExit("Pass --token or set GITLAB_RUNNER_TOKEN")
    url = env.get("GITLAB_EXTERNAL_URL", gitlab_url())
    cmd = [
        "sudo",
        "gitlab-runner",
        "register",
        "--non-interactive",
        "--url",
        url,
        "--token",
        token,
        "--executor",
        "docker",
        "--docker-image",
        "docker:24",
        "--docker-privileged",
        "--docker-volumes",
        "/var/run/docker.sock:/var/run/docker.sock",
        "--description",
        args.description or "fast-git-runner",
        "--tag-list",
        args.tags,
    ]
    return subprocess.call(cmd)


def cmd_runner_status(_: argparse.Namespace) -> int:
    code = subprocess.call(["gitlab-runner", "status"])
    subprocess.call(["gitlab-runner", "list"])
    return code


def cmd_project_create(args: argparse.Namespace) -> int:
    api = GitLabAPI(base_url=args.url, token=args.token)
    project = api.create_project(
        args.name,
        path=args.path,
        visibility=args.visibility,
        description=args.description or "",
    )
    echo(f"created: {project.get('web_url')} (id={project.get('id')})")
    return 0


def cmd_project_list(args: argparse.Namespace) -> int:
    api = GitLabAPI(base_url=args.url, token=args.token)
    projects = api.list_projects()
    print(f"{'ID':<8} {'PATH':<40} URL")
    print("-" * 90)
    for p in projects:
        print(
            f"{p.get('id', ''):<8} {p.get('path_with_namespace', ''):<40} "
            f"{p.get('web_url', '')}"
        )
    echo(f"\n{len(projects)} project(s)")
    return 0


def cmd_project_remove(args: argparse.Namespace) -> int:
    if not args.yes:
        raise SystemExit("Refusing to delete without --yes")
    api = GitLabAPI(base_url=args.url, token=args.token)
    api.delete_project(args.path_or_id)
    echo(f"removed: {args.path_or_id}")
    return 0


def cmd_project_seed(args: argparse.Namespace) -> int:
    result = seed_project(
        args.path,
        profile=args.profile,
        name=args.name,
        visibility=args.visibility,
        remote_name=args.remote,
        force_ci=bool(args.force_ci),
        skip_push=bool(args.skip_push),
        skip_ci=bool(args.skip_ci),
        api=GitLabAPI(base_url=args.url, token=args.token),
    )
    echo("")
    echo(f"seeded: {result['web_url']}")
    return 0


def cmd_deploy_setup(_: argparse.Namespace) -> int:
    echo(
        "Deploy remains each project's concern (__ctrl__/remote/*).\n"
        "After seeding, CI deploy stage calls that project's start-prod.sh.\n"
        "On the target app VM, run that project's: fast-*-ctrl setup | clone | env | start"
    )
    return 0


def cmd_deploy_deploy(_: argparse.Namespace) -> int:
    echo(
        "Trigger deploy via GitLab CI (push to main) or the project's own ctrl CLI:\n"
        "  fast-svelte-ctrl start   # example"
    )
    return 0


def cmd_deploy_status(_: argparse.Namespace) -> int:
    echo("Check the seeded project's GitLab pipelines and the app VM ctrl status.")
    return 0


def cmd_provision(args: argparse.Namespace) -> int:
    """Bootstrap remote host(s) over SSH."""
    if args.host:
        # Ad-hoc host or servers.json id
        try:
            targets = resolve_targets(args.host, include_disabled=True)
        except SystemExit:
            targets = [
                server_from_host(
                    args.host,
                    user=args.user,
                    port=args.port,
                    key=args.key,
                )
            ]
            if args.key:
                targets[0]["key"] = args.key
    else:
        targets = resolve_targets(args.target or "all", include_disabled=args.all_disabled)

    def worker(client, server):
        return provision_remote(
            client,
            server,
            external_url=args.external_url,
            skip_runner=bool(args.skip_runner),
        )

    return _dispatch(targets, worker, parallel=args.parallel)


def cmd_provision_status(args: argparse.Namespace) -> int:
    targets = resolve_targets(args.target, include_disabled=args.all_disabled)

    def worker(client, server):
        return remote_status(client, server)

    return _dispatch(targets, worker, parallel=True)


def _add_api_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--url", default=None, help="GitLab base URL (default: GITLAB_URL / safe/gitlab.url)")
    p.add_argument("--token", default=None, help="API token (default: GITLAB_TOKEN / safe/gitlab.token)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fast-git",
        description=(
            "Turn this machine (or a remote VM) into a GitLab Omnibus + Runner node, "
            "then seed Fast-* projects with CI/CD."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  fast-git setup-local\n"
            "  fast-git setup\n"
            "  fast-git status\n"
            "  fast-git ping all\n"
            "  fast-git project seed ../fast-template/fast-svelte --profile fast-family\n"
            "  fast-git provision 192.168.1.50 --key safe/vm.pem\n"
            "  fast-git flatten --yes\n"
            "  fast-git restore-flat --yes\n"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("list", help="List servers.json targets")
    p.set_defaults(func=cmd_list)

    build_setup_local_subparser(sub)

    p = sub.add_parser("setup", help="In-place: Docker + UFW + GitLab Omnibus + Runner")
    p.add_argument("--external-url", default=None, help="e.g. http://gitlab.example.com")
    p.add_argument("--skip-runner", action="store_true")
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("status", help="Health of GitLab, Runner, Docker on this machine")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("ping", help="Ping SSH hosts and print hostname")
    _add_target(p)
    p.set_defaults(func=cmd_ping)

    p = sub.add_parser("connect", help="Open interactive SSH to one server")
    _add_target(p, default="local")
    p.set_defaults(func=cmd_connect)

    p = sub.add_parser("exec", help="Run a remote shell command")
    _add_target(p)
    p.add_argument("cmd")
    p.add_argument("--in-project", action="store_true")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--parallel", action="store_true")
    p.set_defaults(func=cmd_exec)

    # gitlab
    g = sub.add_parser("gitlab", help="GitLab Omnibus operations")
    g_sub = g.add_subparsers(dest="gitlab_cmd")

    p = g_sub.add_parser("install", help="Install/reconfigure GitLab Omnibus (no runner)")
    p.add_argument("--external-url", default=None)
    p.set_defaults(func=cmd_gitlab_install)

    p = g_sub.add_parser("status", help="GitLab status")
    p.set_defaults(func=cmd_gitlab_status)

    p = g_sub.add_parser("restart", help="gitlab-ctl restart")
    p.set_defaults(func=cmd_gitlab_restart)

    p = g_sub.add_parser("backup", help="Create Omnibus backup + /etc/gitlab tarball")
    p.set_defaults(func=cmd_gitlab_backup)

    # runner
    r = sub.add_parser("runner", help="GitLab Runner operations")
    r_sub = r.add_subparsers(dest="runner_cmd")

    p = r_sub.add_parser("install", help="Ensure Runner package is installed")
    p.set_defaults(func=cmd_runner_install)

    p = r_sub.add_parser("register", help="Register runner (non-interactive)")
    p.add_argument("--token", required=True)
    p.add_argument("--url", default=None)
    p.add_argument("--tags", default="docker,deploy")
    p.add_argument("--description", default=None)
    p.set_defaults(func=cmd_runner_register)

    p = r_sub.add_parser("status", help="Runner service + list")
    p.set_defaults(func=cmd_runner_status)

    # project
    proj = sub.add_parser("project", help="GitLab project create / seed / list / remove")
    p_sub = proj.add_subparsers(dest="project_cmd")

    p = p_sub.add_parser("create", help="Create bare GitLab project")
    _add_api_flags(p)
    p.add_argument("name")
    p.add_argument("--path", default=None)
    p.add_argument("--visibility", default="private", choices=["private", "internal", "public"])
    p.add_argument("--description", default="")
    p.set_defaults(func=cmd_project_create)

    p = p_sub.add_parser("seed", help="Create project, write CI, push local repo")
    _add_api_flags(p)
    p.add_argument("path", help="Local project directory")
    p.add_argument("--profile", default="generic", help="fast-family | python | docker | generic")
    p.add_argument("--name", default=None, help="GitLab project name (default: folder name)")
    p.add_argument("--visibility", default="private", choices=["private", "internal", "public"])
    p.add_argument("--remote", default="gitlab", help="git remote name")
    p.add_argument("--force-ci", action="store_true", help="Overwrite existing .gitlab-ci.yml")
    p.add_argument("--skip-push", action="store_true")
    p.add_argument("--skip-ci", action="store_true")
    p.set_defaults(func=cmd_project_seed)

    p = p_sub.add_parser("list", help="List GitLab projects")
    _add_api_flags(p)
    p.set_defaults(func=cmd_project_list)

    p = p_sub.add_parser("remove", help="Delete a GitLab project")
    _add_api_flags(p)
    p.add_argument("path_or_id")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_project_remove)

    # deploy (thin stubs — real deploy lives in each project's __ctrl__)
    d = sub.add_parser("deploy", help="Pointers to per-project deploy (not reimplemented here)")
    d_sub = d.add_subparsers(dest="deploy_cmd")
    for name, fn, help_ in [
        ("setup", cmd_deploy_setup, "How to prepare an app VM"),
        ("deploy", cmd_deploy_deploy, "How to trigger deploy"),
        ("status", cmd_deploy_status, "Where to check deploy status"),
    ]:
        p = d_sub.add_parser(name, help=help_)
        p.set_defaults(func=fn)

    # provision
    p = sub.add_parser("provision", help="Bootstrap a remote box over SSH")
    p.add_argument(
        "host",
        nargs="?",
        default=None,
        help="IP/hostname or servers.json id (default: use --target)",
    )
    p.add_argument("--target", default=None, help="servers.json selector (id or 'all')")
    p.add_argument("--user", default="ubuntu")
    p.add_argument("--port", type=int, default=22)
    p.add_argument("--key", default=None, help="SSH private key path")
    p.add_argument("--external-url", default=None)
    p.add_argument("--skip-runner", action="store_true")
    p.add_argument("--parallel", action="store_true")
    p.add_argument("--all-disabled", action="store_true")
    p.set_defaults(func=cmd_provision)

    build_flatten_subparser(sub)
    build_restore_flat_subparser(sub)

    return parser


def _repl() -> int:
    parser = build_parser()
    echo(
        "fast-git> (setup-local | setup | status | ping | flatten --yes | "
        "project seed <path> | provision <host> | quit)"
    )
    while True:
        try:
            line = input("fast-git> ").strip()
        except (EOFError, KeyboardInterrupt):
            echo("")
            return 0
        if not line:
            continue
        if line.lower() in {"quit", "exit", "q"}:
            return 0
        try:
            args = parser.parse_args(line.split())
        except SystemExit:
            continue
        if not getattr(args, "func", None):
            parser.print_help()
            continue
        try:
            code = args.func(args)
            if code:
                echo(f"(exit {code})")
        except SystemExit as exc:
            if exc.code not in (0, None):
                echo(str(exc))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return _repl()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        # Nested subcommands without action → help
        parser.print_help()
        return 2
    # Allow --token on API commands to override file without requiring env
    if getattr(args, "token", None):
        import os

        os.environ["GITLAB_TOKEN"] = args.token
    if getattr(args, "url", None):
        import os

        os.environ["GITLAB_URL"] = args.url
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
