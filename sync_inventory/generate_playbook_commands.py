#!/usr/bin/env python3
"""Generate one ansible-playbook command script per role assigned to each env.

For every env with hosts in --hosts-file, and every role assigned to that
env, write an executable script at commands/<env>_<role>.sh that runs the
matching playbook from that branch's checkout:

    ansible-playbook repo/<env>/playbooks/<role>.yml

No --limit is passed by default -- the playbook's own `hosts:` key decides
which host(s)/group(s) it targets, the same way it would if a human ran
ansible-playbook by hand. Each script takes an optional first argument that
adds `--limit <host-or-group>` on top of whatever the playbook already
targets, e.g. `commands/<env>_<role>.sh some-host.example.com` narrows the
run to just that host -- this is what run-play's -H/--host uses under the
hood.

No -i/--inventory is passed by default either -- each branch's own
ansible.cfg (see below) already declares its own inventory file, so
Ansible finds it on its own. It can still be overridden by exporting
INVENTORY before running the script, e.g.
`INVENTORY=other/hosts.yml commands/<env>_<role>.sh` -- this is what
run-play's -i/--inventory uses under the hood.

Each script is self-contained and safe to run directly (e.g. to debug one
command by hand) -- its output goes straight to stdout/stderr, nothing is
redirected to a log file by the script itself. run-play runs one or every
script in --commands-dir and handles logging/failure-tracking itself.

If a branch isn't checked out under repo/, an error is reported for that env
and its commands are skipped. A role whose playbook file doesn't actually
exist in that branch's checkout is reported as a warning and skipped (the
netbox data only records intent, not what playbooks actually exist).

If that branch has its own ansible.cfg, ANSIBLE_CONFIG is set to it for that
command (Ansible only auto-discovers ansible.cfg via the current directory,
not the playbook's path, so without this the branch's own config -- vault
password file, remote_user, inventory, etc. -- would otherwise be silently
ignored). If install-requirements has installed that branch's
roles/collections into <branch>/.ansible/{roles,collections},
ANSIBLE_ROLES_PATH and ANSIBLE_COLLECTIONS_PATH are set to them too.

Every run first removes any existing scripts in --commands-dir, so a role
that no longer applies doesn't leave a stale script behind.
"""

import argparse
import json
import shutil
import stat
from collections import defaultdict
from pathlib import Path

from sync_inventory.naming import sanitize_dir_name


def load_hosts(hosts_file, verbose=False):
    try:
        with open(hosts_file) as f:
            return json.load(f)
    except FileNotFoundError:
        if verbose:
            print(f"warning: hosts file '{hosts_file}' not found; treating as empty")
        return {}


def sanitize_env_name(env, verbose=False):
    """Match pull-repo's branch-directory sanitization, so repo/<branch>/
    refers to the same branch for a feature branch like
    "pttran3/SVCPLAN-1234/test"."""
    sanitized = sanitize_dir_name(env)
    if sanitized != env and verbose:
        print(f"warning: env '{env}' has invalid directory characters; using '{sanitized}' instead")
    return sanitized


def group_by_env(hosts, verbose=False):
    envs = defaultdict(lambda: defaultdict(list))
    for hostname, meta in hosts.items():
        env = sanitize_env_name(meta["env"], verbose=verbose)
        envs[env][meta["role"]].append(hostname)
    return envs


def write_command_script(path, env_vars, playbook_path, verbose=False):
    export_lines = [f"export {key}={value}" for key, value in env_vars.items()]
    lines = [
        "#!/bin/bash",
        *export_lines,
        "extra_args=()",
        'if [[ -n "$1" ]]; then',
        '  extra_args+=(--limit "$1")',
        "fi",
        'if [[ -n "$INVENTORY" ]]; then',
        '  extra_args+=(-i "$INVENTORY")',
        "fi",
        f'ansible-playbook "${{extra_args[@]}}" {playbook_path}',
        "",
    ]
    path.write_text("\n".join(lines))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    if verbose:
        print(f"Wrote {path}")


def generate_playbook_commands(hosts_file="hosts.json", repo_dir="repo", commands_dir="commands", verbose=False):
    repo_dir = Path(repo_dir)
    commands_dir = Path(commands_dir)

    if commands_dir.is_dir():
        shutil.rmtree(commands_dir)
    commands_dir.mkdir(parents=True, exist_ok=True)

    hosts = load_hosts(hosts_file, verbose=verbose)
    envs = group_by_env(hosts, verbose=verbose)

    for branch, roles in sorted(envs.items()):
        branch_dir = repo_dir / branch

        if not branch_dir.is_dir():
            if verbose:
                print(f"ERROR: branch '{branch}' not found under {repo_dir} (expected {branch_dir})")
            continue

        env_vars = {}
        ansible_cfg = branch_dir / "ansible.cfg"
        if ansible_cfg.is_file():
            env_vars["ANSIBLE_CONFIG"] = str(ansible_cfg)
        roles_path = branch_dir / ".ansible" / "roles"
        if roles_path.is_dir():
            env_vars["ANSIBLE_ROLES_PATH"] = str(roles_path)
        collections_path = branch_dir / ".ansible" / "collections"
        if collections_path.is_dir():
            env_vars["ANSIBLE_COLLECTIONS_PATH"] = str(collections_path)

        for role in sorted(roles):
            playbook_path = branch_dir / "playbooks" / f"{role}.yml"
            if not playbook_path.is_file():
                if verbose:
                    print(f"WARNING: role '{role}' has no playbook at {playbook_path}; skipping")
                continue
            script_path = commands_dir / f"{branch}_{role}.sh"
            write_command_script(script_path, env_vars, playbook_path, verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--hosts-file", default="hosts.json",
        help="Path to the netbox-style hosts JSON file, to determine which roles are assigned to each env (default: %(default)s)",
    )
    parser.add_argument(
        "--repo-dir", default="repo",
        help="Directory containing per-branch checkouts (default: %(default)s)",
    )
    parser.add_argument(
        "--commands-dir", default="commands",
        help="Directory to write one script per ansible-playbook command into (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print branch/role warnings and errors, and each script written")
    args = parser.parse_args()

    generate_playbook_commands(args.hosts_file, args.repo_dir, args.commands_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
