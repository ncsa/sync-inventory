#!/usr/bin/env python3
"""Generate one Ansible inventory directory per env from a netbox-style hosts JSON file.

Each env gets its own subdirectory under --inventory-dir:

    inventory/<env>/hosts.yml        - the generated inventory
    inventory/<env>/group_vars/      - copied from repo/<env>/inventory/group_vars/, if present
    inventory/<env>/host_vars/       - copied from repo/<env>/inventory/host_vars/, if present

This matters because Ansible discovers group_vars/host_vars relative to the
directory containing the inventory file passed to -i, not the playbook
being run. Keeping the generated hosts.yml, group_vars, and host_vars
together per env means the real per-branch group_vars/host_vars in the
playbook repo actually get applied, and keeping each env in its own
subdirectory (rather than one shared group_vars/ for every env) avoids
different envs' same-named groups colliding with different values.

Every run first removes any existing per-env subdirectories, then writes
fresh ones for envs currently present in the hosts file. This keeps the
directory in sync even when an env loses all its hosts (its subdirectory
is removed rather than left behind). A missing hosts file is treated the
same as an empty one (zero hosts, --inventory-dir ends up empty) rather
than raising an error. Role values become Ansible group names, which may
only contain letters, digits, and underscores; any other character (e.g.
a hyphen or dot) is replaced with an underscore before use. Env values
become a directory name, so "/" and "-" are replaced with "_" the same
way pull-repo sanitizes branch directory names, keeping repo/<branch>/
and inventory/<env>/ referring to the same branch.
"""

import argparse
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

import yaml

from sync_inventory.naming import sanitize_dir_name

INVALID_GROUP_CHARS = re.compile(r"[^A-Za-z0-9_]")


def load_hosts(hosts_file, verbose=False):
    try:
        with open(hosts_file) as f:
            return json.load(f)
    except FileNotFoundError:
        if verbose:
            print(f"warning: hosts file '{hosts_file}' not found; treating as empty")
        return {}


def sanitize_group_name(role, verbose=False):
    """Ansible group names may only contain [A-Za-z0-9_]; replace anything else with _."""
    sanitized = INVALID_GROUP_CHARS.sub("_", role)
    if sanitized != role and verbose:
        print(f"warning: role '{role}' has invalid group-name characters; using '{sanitized}' instead")
    return sanitized


def sanitize_env_name(env, verbose=False):
    """Match pull-repo's branch-directory sanitization, so repo/<branch>/ and
    inventory/<env>/ refer to the same branch for a feature branch like
    "pttran3/SVCPLAN-1234/test"."""
    sanitized = sanitize_dir_name(env)
    if sanitized != env and verbose:
        print(f"warning: env '{env}' has invalid directory characters; using '{sanitized}' instead")
    return sanitized


def group_by_env(hosts, verbose=False):
    envs = defaultdict(lambda: defaultdict(list))
    for hostname, meta in hosts.items():
        env = sanitize_env_name(meta["env"], verbose=verbose)
        role = sanitize_group_name(meta["role"], verbose=verbose)
        envs[env][role].append(hostname)
    return envs


def copy_vars(env_source_dir, env_dir, subdir_name, verbose=False):
    src = env_source_dir / subdir_name
    dest = env_dir / subdir_name
    if not src.is_dir():
        return
    shutil.copytree(src, dest)
    if verbose:
        print(f"Copied {src} -> {dest}")


def write_inventory(env, roles, inventory_dir, repo_dir, verbose=False):
    env_dir = inventory_dir / env
    env_dir.mkdir(parents=True, exist_ok=True)

    inventory = {
        "all": {
            "children": {
                role: {"hosts": {hostname: None for hostname in sorted(hostnames)}}
                for role, hostnames in sorted(roles.items())
            }
        }
    }

    out_path = env_dir / "hosts.yml"
    with open(out_path, "w") as f:
        yaml.safe_dump(inventory, f, sort_keys=False)
    if verbose:
        print(f"Wrote {out_path}")

    repo_inventory_dir = repo_dir / env / "inventory"
    copy_vars(repo_inventory_dir, env_dir, "group_vars", verbose=verbose)
    copy_vars(repo_inventory_dir, env_dir, "host_vars", verbose=verbose)


def generate_inventory(hosts_file="hosts.json", inventory_dir="inventory", repo_dir="repo", verbose=False):
    inventory_dir = Path(inventory_dir)
    repo_dir = Path(repo_dir)
    inventory_dir.mkdir(parents=True, exist_ok=True)

    for stale in inventory_dir.iterdir():
        if stale.is_dir():
            shutil.rmtree(stale)
            if verbose:
                print(f"Removed stale {stale}")

    hosts = load_hosts(hosts_file, verbose=verbose)
    envs = group_by_env(hosts, verbose=verbose)
    for env, roles in envs.items():
        write_inventory(env, roles, inventory_dir, repo_dir, verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--hosts-file", default="hosts.json",
        help="Path to the netbox-style hosts JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--inventory-dir", default="inventory",
        help="Directory to write per-env inventory subdirectories into (default: %(default)s)",
    )
    parser.add_argument(
        "--repo-dir", default="repo",
        help="Directory containing per-branch checkouts, to copy each env's real group_vars/host_vars from (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each inventory file written and vars copied")
    args = parser.parse_args()

    generate_inventory(args.hosts_file, args.inventory_dir, args.repo_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
