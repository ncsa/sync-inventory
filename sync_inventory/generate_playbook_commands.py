#!/usr/bin/env python3
"""Generate one ansible-playbook command script per role assigned to each env.

For every env with hosts in --hosts-file, and every role assigned to that
env, write an executable script at commands/<env>_<role>.sh that runs the
matching playbook from that branch's checkout:

    ansible-playbook -i inventory/<env>/hosts.yml repo/<env>/playbooks/<role>.yml

No --limit is passed by default -- the playbook's own `hosts:` key decides
which group(s) it targets (ordinary Ansible usage; see generate-inventory
for how nested groups, via group_structure/<role>.yml, let a role target
several groups at once). Each script takes an optional first argument that
adds `--limit <host>` on top of whatever the playbook already targets, e.g.
`commands/<env>_<role>.sh some-host.example.com` runs just that host --
this is what run-play's -H/--host uses under the hood. The inventory file
can likewise be overridden by exporting INVENTORY before running the
script, e.g. `INVENTORY=other/hosts.yml commands/<env>_<role>.sh` -- this
is what run-play's -i/--inventory uses under the hood.

Each script is self-contained and safe to run directly (e.g. to debug one
command by hand) -- its output goes straight to stdout/stderr, nothing is
redirected to a log file by the script itself. run-play runs one or every
script in --commands-dir and handles logging/failure-tracking itself.

If a branch isn't checked out under repo/, an error is reported for that env
and its commands are skipped. A role assigned to that env whose playbook
file doesn't actually exist in that branch's checkout is reported (to
stderr, always -- not just with --verbose) and skipped rather than
stopping everything else, since the netbox data only records intent, not
what playbooks actually exist.

If that branch has its own ansible.cfg, ANSIBLE_CONFIG is set to it for that
command (Ansible only auto-discovers ansible.cfg via the current directory,
not the playbook's path, so without this the branch's own config -- vault
password file, remote_user, etc. -- would otherwise be silently ignored).
If install-requirements has installed that branch's roles/collections into
<branch>/.ansible/{roles,collections}, ANSIBLE_ROLES_PATH and
ANSIBLE_COLLECTIONS_PATH are set to them too.

Every run first removes any existing scripts in --commands-dir, so a role
that no longer applies doesn't leave a stale script behind.
"""

import argparse
import shutil
import stat
import sys
from pathlib import Path

from sync_inventory.generate_inventory import group_by_env, load_hosts


def write_command_script(path, env_vars, inventory_path, playbook_path, verbose=False):
    export_lines = [f"export {key}={value}" for key, value in env_vars.items()]
    lines = [
        "#!/bin/bash",
        *export_lines,
        f'INVENTORY="${{INVENTORY:-{inventory_path}}}"',
        f"PLAYBOOK={playbook_path}",
        "extra_args=()",
        'if [[ -n "$1" ]]; then',
        '  extra_args=(--limit "$1")',
        "fi",
        'ansible-playbook -i "$INVENTORY" "${extra_args[@]}" "$PLAYBOOK"',
        "",
    ]
    path.write_text("\n".join(lines))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    if verbose:
        print(f"Wrote {path}")


def generate_playbook_commands(inventory_dir="inventory", repo_dir="repo", commands_dir="commands", hosts_file="hosts.json", verbose=False):
    inventory_dir = Path(inventory_dir)
    repo_dir = Path(repo_dir)
    commands_dir = Path(commands_dir)

    if commands_dir.is_dir():
        shutil.rmtree(commands_dir)
    commands_dir.mkdir(parents=True, exist_ok=True)

    hosts = load_hosts(hosts_file, verbose=verbose)
    envs = group_by_env(hosts, verbose=verbose)

    for env_dir in sorted(p for p in inventory_dir.iterdir() if p.is_dir()):
        branch = env_dir.name
        inventory_path = env_dir / "hosts.yml"
        branch_dir = repo_dir / branch

        if not inventory_path.is_file():
            if verbose:
                print(f"ERROR: no hosts.yml found under {env_dir}")
            continue

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

        for role in sorted(envs.get(branch, {}).keys()):
            playbook_path = branch_dir / "playbooks" / f"{role}.yml"
            if not playbook_path.is_file():
                print(f"warning: role '{role}' has no playbook at {playbook_path}; skipping", file=sys.stderr)
                continue
            script_path = commands_dir / f"{branch}_{role}.sh"
            write_command_script(script_path, env_vars, inventory_path, playbook_path, verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--inventory-dir", default="inventory",
        help="Directory containing per-env inventory subdirectories (default: %(default)s)",
    )
    parser.add_argument(
        "--repo-dir", default="repo",
        help="Directory containing per-branch checkouts (default: %(default)s)",
    )
    parser.add_argument(
        "--commands-dir", default="commands",
        help="Directory to write one script per ansible-playbook command into (default: %(default)s)",
    )
    parser.add_argument(
        "--hosts-file", default="hosts.json",
        help="Path to the netbox-style hosts JSON file, to determine which roles are assigned to each env (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each script written (missing-playbook warnings always print, regardless of this flag)")
    args = parser.parse_args()

    generate_playbook_commands(args.inventory_dir, args.repo_dir, args.commands_dir, args.hosts_file, verbose=args.verbose)


if __name__ == "__main__":
    main()
