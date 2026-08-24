#!/usr/bin/env python3
"""Generate ansible-playbook commands for each group in each env inventory.

Each file in output/ is named after an env, which is expected to match a
branch checked out under repo/ (see pull-repo). For each group (role
name) found in that inventory file, emit a command that runs the matching
playbook from that branch's checkout, limited to that group:

    ansible-playbook -i output/<env>.yml --limit <group> repo/<env>/playbooks/<group>.yml

If a branch isn't checked out under repo/, an error is reported for that env
and its commands are skipped. Groups whose playbook file doesn't actually
exist in that branch's checkout are reported as a warning and skipped (the
netbox data only records intent, not what playbooks actually exist). Writes
the resulting
commands to commands.sh. Each command's combined stdout/stderr goes to its
own dedicated log file under --logs-dir, named <env>_<group>.log.
"""

import argparse
from pathlib import Path

import yaml


def groups_in_inventory(inventory_path):
    with open(inventory_path) as f:
        inventory = yaml.safe_load(f)
    return list(inventory["all"]["children"].keys())


def generate_playbook_commands(inventory_dir="inventory", repo_dir="repo", commands_file="commands.sh", logs_dir="logs", verbose=False):
    inventory_dir = Path(inventory_dir)
    repo_dir = Path(repo_dir)
    commands_file = Path(commands_file)

    lines = [
        "#!/bin/bash",
        "set -uo pipefail",
        "",
        f'logs_dir="{logs_dir}"',
        'mkdir -p "$logs_dir"',
        "",
        "failures=0",
        "run() {",
        "  local log_file=\"$1\"; shift",
        '  echo "+ $* (log: $log_file)"',
        '  if ! "$@" &> "$log_file"; then',
        '    echo "FAILED: $* (see $log_file)" >&2',
        "    failures=$((failures + 1))",
        "  fi",
        "}",
        "",
    ]

    for inventory_path in sorted(inventory_dir.glob("*.yml")):
        branch = inventory_path.stem
        branch_dir = repo_dir / branch

        if not branch_dir.is_dir():
            if verbose:
                print(f"ERROR: branch '{branch}' not found under {repo_dir} (expected {branch_dir})")
            continue

        for group in groups_in_inventory(inventory_path):
            playbook_path = branch_dir / "playbooks" / f"{group}.yml"
            if not playbook_path.is_file():
                if verbose:
                    print(f"WARNING: role '{group}' has no playbook at {playbook_path}; skipping")
                continue
            log_file = f'"$logs_dir/{branch}_{group}.log"'
            lines.append(f"run {log_file} ansible-playbook -i {inventory_path} --limit {group} {playbook_path}")

    lines += [
        "",
        'if [[ "$failures" -gt 0 ]]; then',
        '  echo "$failures command(s) failed" >&2',
        "  exit 1",
        "fi",
    ]

    commands_file.write_text("\n".join(lines) + "\n")
    if verbose:
        print(f"Wrote {commands_file}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inventory-dir", default="inventory",
        help="Directory containing per-env inventory YAML files (default: %(default)s)",
    )
    parser.add_argument(
        "--repo-dir", default="repo",
        help="Directory containing per-branch checkouts (default: %(default)s)",
    )
    parser.add_argument(
        "--commands-file", default="commands.sh",
        help="Where to write the generated ansible-playbook commands (default: %(default)s)",
    )
    parser.add_argument(
        "--logs-dir", default="logs",
        help="Directory to write a dedicated log file per ansible-playbook command (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print branch/role warnings and errors, and the final Wrote message")
    args = parser.parse_args()

    generate_playbook_commands(args.inventory_dir, args.repo_dir, args.commands_file, args.logs_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
