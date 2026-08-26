#!/usr/bin/env python3
"""Generate one ansible-playbook command script per group in each env inventory.

Each subdirectory of --inventory-dir is named after an env, which is
expected to match a branch checked out under repo/ (see pull-repo). For
each group (role name) found in that env's inventory/<env>/hosts.yml, write
an executable script at commands/<env>_<group>.sh that runs the matching
playbook from that branch's checkout, limited to that group by default:

    ansible-playbook -i inventory/<env>/hosts.yml --limit <group> repo/<env>/playbooks/<group>.yml

Each script takes an optional first argument overriding what --limit is
passed, e.g. `commands/<env>_<group>.sh some-host.example.com` runs just
that host instead of the whole group -- this is what run-play's -H/--host
uses under the hood.

Each script is self-contained and safe to run directly (e.g. to debug one
command by hand) -- its output goes straight to stdout/stderr, nothing is
redirected to a log file by the script itself. run-play runs one or every
script in --commands-dir and handles logging/failure-tracking itself.

If a branch isn't checked out under repo/, an error is reported for that env
and its commands are skipped. Groups whose playbook file doesn't actually
exist in that branch's checkout are reported as a warning and skipped (the
netbox data only records intent, not what playbooks actually exist).

If that branch has its own ansible.cfg, ANSIBLE_CONFIG is set to it for that
command (Ansible only auto-discovers ansible.cfg via the current directory,
not the playbook's path, so without this the branch's own config -- vault
password file, remote_user, etc. -- would otherwise be silently ignored).
If install-requirements has installed that branch's roles/collections into
<branch>/.ansible/{roles,collections}, ANSIBLE_ROLES_PATH and
ANSIBLE_COLLECTIONS_PATH are set to them too.

Every run first removes any existing scripts in --commands-dir, so a group
that no longer applies doesn't leave a stale script behind.
"""

import argparse
import shutil
import stat
from pathlib import Path

import yaml


def groups_in_inventory(inventory_path):
    with open(inventory_path) as f:
        inventory = yaml.safe_load(f)
    return list(inventory["all"]["children"].keys())


def write_command_script(path, env_vars, ansible_cmd, verbose=False):
    export_lines = [f"export {key}={value}" for key, value in env_vars.items()]
    lines = ["#!/bin/bash", *export_lines, ansible_cmd, ""]
    path.write_text("\n".join(lines))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    if verbose:
        print(f"Wrote {path}")


def generate_playbook_commands(inventory_dir="inventory", repo_dir="repo", commands_dir="commands", verbose=False):
    inventory_dir = Path(inventory_dir)
    repo_dir = Path(repo_dir)
    commands_dir = Path(commands_dir)

    if commands_dir.is_dir():
        shutil.rmtree(commands_dir)
    commands_dir.mkdir(parents=True, exist_ok=True)

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

        for group in groups_in_inventory(inventory_path):
            playbook_path = branch_dir / "playbooks" / f"{group}.yml"
            if not playbook_path.is_file():
                if verbose:
                    print(f"WARNING: role '{group}' has no playbook at {playbook_path}; skipping")
                continue
            ansible_cmd = f'ansible-playbook -i {inventory_path} --limit "${{1:-{group}}}" {playbook_path}'
            script_path = commands_dir / f"{branch}_{group}.sh"
            write_command_script(script_path, env_vars, ansible_cmd, verbose=verbose)


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
    parser.add_argument("-v", "--verbose", action="store_true", help="Print branch/role warnings and errors, and each script written")
    args = parser.parse_args()

    generate_playbook_commands(args.inventory_dir, args.repo_dir, args.commands_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
