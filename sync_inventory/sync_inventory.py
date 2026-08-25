#!/usr/bin/env python3
"""Sync inventory: fetch metadata, pull each branch, regenerate inventories, regenerate commands.

Steps:
  1. fetch-meta  - refresh the netbox-style hosts file from NetBox (nbmeta metadata)
  2. pull-repo   - mirror each branch of the git repo into repo/<branch>/
  3. install-requirements - install each branch's roles/collections from its
     requirements.yml into repo/<branch>/.ansible/{roles,collections}
  4. generate-inventory - rebuild inventory/<env>/hosts.yml from the hosts file,
     copying that branch's real group_vars/host_vars in alongside it
  5. generate-playbook-commands - rebuild commands.sh from inventory/ + repo/,
     pointing each command's ANSIBLE_CONFIG/ANSIBLE_ROLES_PATH/
     ANSIBLE_COLLECTIONS_PATH at that branch's own config and installed deps

A failure in step 1, 2, or 3 (e.g. NetBox/network unreachable) does not
block the rest, since steps 4/5 just need whatever hosts file / repo
checkouts / installed dependencies already exist on disk. Quiet by
default: routine progress and warning/error messages are only printed
with --verbose. Refuses to run if another instance is already in progress
(lock: .sync_inventory.lock in the current directory) regardless of
verbosity.
"""

import argparse
import subprocess
from pathlib import Path

from sync_inventory.fetch_meta import fetch_meta
from sync_inventory.generate_inventory import generate_inventory
from sync_inventory.generate_playbook_commands import generate_playbook_commands
from sync_inventory.install_requirements import install_requirements
from sync_inventory.pull_repo import pull_repo

LOCK_DIR = Path(".sync_inventory.lock")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-u", "--repo-url", required=True,
        help="Git repo to mirror branches from",
    )
    parser.add_argument("-r", "--repo-dir", default="repo", help="Where branch checkouts are written (default: %(default)s)")
    parser.add_argument("-i", "--inventory-dir", default="inventory", help="Where generated per-env inventories are written (default: %(default)s)")
    parser.add_argument("-n", "--hosts-file", default="hosts.json", help="NetBox-style hosts JSON (default: %(default)s)")
    parser.add_argument("-c", "--commands-file", default="commands.sh", help="Where generated ansible-playbook commands are written (default: %(default)s)")
    parser.add_argument("-l", "--logs-dir", default="logs", help="Where each ansible-playbook command writes its own log file (default: %(default)s)")
    parser.add_argument("--run", action="store_true", help="Also execute the generated commands file (real ansible-playbook runs)")
    parser.add_argument(
        "--skip-fetch-meta", action="store_true",
        help="Don't refresh the hosts file from NetBox; use it as-is on disk",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print routine progress plus warning/error messages (quiet by default)",
    )
    args = parser.parse_args()

    try:
        LOCK_DIR.mkdir()
    except FileExistsError:
        raise SystemExit(
            f"Another sync-inventory is already in progress (lock: {LOCK_DIR}). Exiting.\n"
            f"If no other run is actually in progress (e.g. a previous run was killed), "
            f"remove the stale lock with: rmdir {LOCK_DIR}"
        )

    try:
        if not args.skip_fetch_meta:
            try:
                fetch_meta(args.hosts_file, verbose=args.verbose)
            except Exception as e:
                if args.verbose:
                    print(f"WARNING: fetch-meta failed ({e}); continuing with existing {args.hosts_file}")

        try:
            pull_repo(args.repo_url, args.repo_dir, verbose=args.verbose)
        except Exception as e:
            if args.verbose:
                print(f"WARNING: pull-repo failed ({e}); continuing with existing {args.repo_dir}/ state")

        try:
            install_requirements(args.repo_dir, verbose=args.verbose)
        except Exception as e:
            if args.verbose:
                print(f"WARNING: install-requirements failed ({e}); continuing with existing {args.repo_dir}/ dependencies")

        generate_inventory(args.hosts_file, args.inventory_dir, args.repo_dir, verbose=args.verbose)
        generate_playbook_commands(args.inventory_dir, args.repo_dir, args.commands_file, args.logs_dir, verbose=args.verbose)

        if args.run:
            subprocess.run(["bash", args.commands_file], check=True)
    finally:
        LOCK_DIR.rmdir()


if __name__ == "__main__":
    main()
