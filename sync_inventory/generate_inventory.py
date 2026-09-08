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
than raising an error.

By default, a role gets one flat Ansible group named after the role itself
(deliberately not sanitized -- Ansible will warn about invalid group-name
characters itself if a role has any). If repo/<branch>/group_structure/
has a <role>.yml file for that role, its (nested) group shape is used
instead -- see build_group_tree() below. That file lives in the playbook
repo itself, alongside playbooks/, requirements.yml, and ansible.cfg, so
each branch can have its own copy (same as those). Env values become a
directory name, so "/" and "-" are replaced with "_" the same way
pull-repo sanitizes branch directory names, keeping repo/<branch>/ and
inventory/<env>/ referring to the same branch.

group_structure/<role>.yml format: a nested YAML mapping with no wrapper
key -- the file's own top level *is* the set of top-level sibling groups,
e.g. group_structure/proxmox.yml:

    proxmox:
    proxmox_test:
      proxmox_test_one:
      proxmox_test_two:
    proxmox_00:

proxmox/proxmox_test/proxmox_00 are three independent top-level siblings
(not one root per role); proxmox_test additionally nests two children of
its own. Group names don't need to relate to their parent's name in any
way -- there's no naming convention enforced, just the tree shape itself.

Every node in the file becomes a real group in the generated inventory,
whether or not it currently has any hosts -- this matters because a host
several levels deep (e.g. proxmox_test_one) needs its ancestors to still
exist for Ansible's children: chain to carry group_vars inheritance down
to it. A host lands in the node named by its NetBox "group" metadata field
(see fetch-meta); with no "group" set, it falls back to the node named
after its own role -- so a top-level sibling literally named after the
role (e.g. "proxmox" in group_structure/proxmox.yml) is expected to exist.
A "group" that doesn't match any node in the tree is dropped rather than
silently misplaced.

A missing structure file just means flat single-group behavior for that
role -- quietly, unless some host of that role has an explicit "group" set
anyway (e.g. left over from before the file was removed, or set too
early), in which case a warning is printed since that "group" is being
silently ignored. A file that exists but is invalid in some way (a
non-mapping top-level shape, a repeated group name, or missing the
role-name group hosts fall back to) also falls back to flat behavior for
that role, but prints a warning to stderr -- always, not just with
--verbose -- since that's a real config problem worth noticing.
"""

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import yaml

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
    """Match pull-repo's branch-directory sanitization, so repo/<branch>/ and
    inventory/<env>/ refer to the same branch for a feature branch like
    "pttran3/SVCPLAN-1234/test"."""
    sanitized = sanitize_dir_name(env)
    if sanitized != env and verbose:
        print(f"warning: env '{env}' has invalid directory characters; using '{sanitized}' instead")
    return sanitized


def group_by_env(hosts, verbose=False):
    envs = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for hostname, meta in hosts.items():
        env = sanitize_env_name(meta["env"], verbose=verbose)
        role = meta["role"]
        group_name = meta.get("group") or role
        envs[env][role][group_name].append(hostname)
    return envs


def load_group_structure(role, group_structure_dir):
    """Load and validate group_structure_dir/<role>.yml. Returns the tree (a
    dict of group_name -> nested dict or None) directly -- there's no
    wrapper key, the file's own top level *is* the set of top-level
    sibling groups. Returns None if the file doesn't exist or isn't a
    valid structure file (missing/malformed, falls back to flat behavior
    for that role -- a warning is printed to stderr either way, except
    when the file simply doesn't exist at all)."""
    path = Path(group_structure_dir) / f"{role}.yml"
    if not path.is_file():
        return None

    with open(path) as f:
        data = yaml.safe_load(f)
    tree = data or {}

    def validate(node, seen):
        if not isinstance(node, dict):
            print(f"warning: {path} is not a valid group structure (expected a mapping of group names); ignoring, using flat group for '{role}'", file=sys.stderr)
            return False
        for name, subtree in node.items():
            if name in seen:
                print(f"warning: {path} has '{name}' repeated in more than one branch; ignoring, using flat group for '{role}'", file=sys.stderr)
                return False
            seen.add(name)
            if subtree is not None and not validate(subtree, seen):
                return False
        return True

    if not validate(tree, set()):
        return None

    if role not in tree:
        print(
            f"warning: {path} has no top-level '{role}' group (needed for hosts with no explicit "
            f"'group' set); ignoring, using flat group for '{role}'",
            file=sys.stderr,
        )
        return None

    return tree


def build_group_tree(tree, host_buckets, seen_names, verbose=False):
    """Recursively build the real Ansible {children: {...}, hosts: {...}} shape
    from a group_structure tree. Every node in `tree` is emitted, whether or
    not it has any hosts -- so a node with hosts several levels deep still
    has its ancestors present for group_vars inheritance. Records every node
    name visited into `seen_names`, so the caller can tell which host
    buckets didn't match any real node."""
    result = {}
    for name, subtree in tree.items():
        seen_names.add(name)
        entry = {}
        if subtree:
            entry["children"] = build_group_tree(subtree, host_buckets, seen_names, verbose=verbose)
        hostnames = host_buckets.get(name)
        if hostnames:
            entry["hosts"] = {hostname: None for hostname in sorted(hostnames)}
        result[name] = entry or None
    return result


def merge_children(children, new_entries, role, sources):
    """Merge a role's top-level group(s) into the env's shared `children` dict.
    Warns and keeps the first entry if two roles both define the same
    top-level group name, rather than silently letting one clobber the other."""
    for name, entry in new_entries.items():
        if name in children:
            print(f"warning: group '{name}' is defined by both role '{sources[name]}' and role '{role}'; keeping '{sources[name]}''s", file=sys.stderr)
            continue
        children[name] = entry
        sources[name] = role


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
    group_structure_dir = repo_dir / env / "group_structure"

    children = {}
    sources = {}
    for role, host_buckets in sorted(roles.items()):
        tree = load_group_structure(role, group_structure_dir)
        if tree is not None:
            seen_names = set()
            built = build_group_tree(tree, host_buckets, seen_names, verbose=verbose)
            for group_name, hostnames in host_buckets.items():
                if group_name not in seen_names:
                    print(
                        f"warning: role '{role}' has no group named '{group_name}' in "
                        f"{group_structure_dir}/{role}.yml; dropping {sorted(hostnames)}",
                        file=sys.stderr,
                    )
            merge_children(children, built, role, sources)
        else:
            for group_name, hostnames in host_buckets.items():
                if group_name != role:
                    print(
                        f"warning: role '{role}' has no {group_structure_dir}/{role}.yml, so 'group: {group_name}' "
                        f"is ignored for {sorted(hostnames)}; using flat group '{role}' instead",
                        file=sys.stderr,
                    )
            all_hostnames = sorted({h for hostnames in host_buckets.values() for h in hostnames})
            merge_children(children, {role: {"hosts": {h: None for h in all_hostnames}}}, role, sources)

    inventory = {"all": {"children": children}}

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
        help="Directory containing per-branch checkouts, to copy each env's real group_vars/host_vars and read its group_structure/ from (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each inventory file written and vars copied (group_structure warnings always print, regardless of this flag)")
    args = parser.parse_args()

    generate_inventory(args.hosts_file, args.inventory_dir, args.repo_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
