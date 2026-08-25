#!/usr/bin/env python3
"""Generate one Ansible YAML inventory per env from a netbox-style hosts JSON file.

Every run first removes any existing *.yml files in --inventory-dir, then
writes a fresh one per env currently present in the hosts file. This keeps
the directory in sync even when an env loses all its hosts (its stale file
is removed rather than left behind). A missing hosts file is treated the
same as an empty one (zero hosts, --inventory-dir ends up empty) rather
than raising an error. Role values become Ansible group names, which may
only contain letters, digits, and underscores; any other character (e.g.
a hyphen or dot) is replaced with an underscore before use.
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

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


def group_by_env(hosts, verbose=False):
    envs = defaultdict(lambda: defaultdict(list))
    for hostname, meta in hosts.items():
        role = sanitize_group_name(meta["role"], verbose=verbose)
        envs[meta["env"]][role].append(hostname)
    return envs


def write_inventory(env, roles, inventory_dir, verbose=False):
    inventory = {
        "all": {
            "children": {
                role: {"hosts": {hostname: None for hostname in sorted(hostnames)}}
                for role, hostnames in sorted(roles.items())
            }
        }
    }

    out_path = inventory_dir / f"{env}.yml"
    with open(out_path, "w") as f:
        yaml.safe_dump(inventory, f, sort_keys=False)
    if verbose:
        print(f"Wrote {out_path}")


def generate_inventory(hosts_file="hosts.json", inventory_dir="inventory", verbose=False):
    inventory_dir = Path(inventory_dir)
    inventory_dir.mkdir(parents=True, exist_ok=True)

    for stale in inventory_dir.glob("*.yml"):
        stale.unlink()
        if verbose:
            print(f"Removed stale {stale}")

    hosts = load_hosts(hosts_file, verbose=verbose)
    envs = group_by_env(hosts, verbose=verbose)
    for env, roles in envs.items():
        write_inventory(env, roles, inventory_dir, verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hosts-file", default="hosts.json",
        help="Path to the netbox-style hosts JSON file (default: %(default)s)",
    )
    parser.add_argument(
        "--inventory-dir", default="inventory",
        help="Directory to write per-env inventory YAML files (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each inventory file written")
    args = parser.parse_args()

    generate_inventory(args.hosts_file, args.inventory_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
