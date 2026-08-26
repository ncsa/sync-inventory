#!/usr/bin/env python3
"""Run one or all generated ansible-playbook command scripts under --commands-dir.

Each script (see generate-playbook-commands) is a standalone, executable
bash script that runs one ansible-playbook command for one env/role, with
its own ANSIBLE_CONFIG/ANSIBLE_ROLES_PATH/ANSIBLE_COLLECTIONS_PATH already
exported. This command runs them (real ansible-playbook runs), logging
each one's combined stdout/stderr to its own file under --logs-dir, named
<script>.log. That output is also printed to stdout as it happens, unless
-q/--quiet is given, in which case it's only written to the log file.

A single host (rather than the whole group) can be targeted with -H/--host,
which is passed through to the script and overrides its default --limit.
Only valid with -s/--script -- not with --all, since that would run every
script against that one host.

Usage:
    run-play -s pttran3_test_branch_proxmox
    run-play -s pttran3_test_branch_proxmox -H some-host.example.com
    run-play --all
    run-play --list
"""

import argparse
import subprocess
import sys
from pathlib import Path


def run_script(script, logs_dir, host=None, quiet=False, verbose=False):
    log_file = logs_dir / f"{script.stem}.log"
    cmd = ["bash", str(script)] + ([host] if host else [])
    if verbose:
        print(f"+ {' '.join(cmd)} (log: {log_file})")
    with open(log_file, "w") as f:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            f.write(line)
            if not quiet:
                sys.stdout.write(line)
        returncode = process.wait()
    if returncode != 0:
        print(f"FAILED: {' '.join(cmd)} (see {log_file})", file=sys.stderr)
        return False
    return True


def list_commands(commands_dir="commands"):
    commands_dir = Path(commands_dir)
    scripts = sorted(p.stem for p in commands_dir.glob("*.sh"))
    if not scripts:
        print(f"No command scripts found under {commands_dir}")
        return
    for name in scripts:
        print(name)


def run_play(script_name=None, run_all=False, commands_dir="commands", logs_dir="logs", host=None, quiet=False, verbose=False):
    if run_all and host:
        raise SystemExit("-H/--host can only be used with -s/--script, not --all")

    commands_dir = Path(commands_dir)
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)

    if run_all:
        scripts = sorted(commands_dir.glob("*.sh"))
        if not scripts:
            raise SystemExit(f"No command scripts found under {commands_dir}")
    else:
        script = commands_dir / f"{script_name}.sh"
        if not script.is_file():
            raise SystemExit(f"No command script found at {script}")
        scripts = [script]

    failures = sum(not run_script(script, logs_dir, host=host, quiet=quiet, verbose=verbose) for script in scripts)
    if failures:
        raise SystemExit(f"{failures} command(s) failed")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-s", "--script", help="Name of a single command script to run (matches <commands-dir>/<name>.sh)")
    group.add_argument("-a", "--all", action="store_true", help="Run every command script under --commands-dir")
    group.add_argument("-l", "--list", action="store_true", help="List available command scripts under --commands-dir and exit")
    parser.add_argument("--commands-dir", default="commands", help="Directory containing generated command scripts (default: %(default)s)")
    parser.add_argument("--logs-dir", default="logs", help="Directory to write each command's log file into (default: %(default)s)")
    parser.add_argument("-H", "--host", help="Limit the run to a single host instead of the script's whole group")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only log output to --logs-dir; don't also print it to stdout")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print each command as it runs")
    args = parser.parse_args()
    if args.all and args.host:
        parser.error("-H/--host can only be used with -s/--script, not --all")

    if args.list:
        list_commands(args.commands_dir)
        return

    run_play(args.script, args.all, args.commands_dir, args.logs_dir, host=args.host, quiet=args.quiet, verbose=args.verbose)


if __name__ == "__main__":
    main()
