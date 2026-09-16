#!/usr/bin/env python3
"""Install each branch's role/collection dependencies via ansible-galaxy, scoped per branch.

For every branch directory under --repo-dir with a requirements.yml, installs
its roles into <branch>/.ansible/roles/ and its collections into
<branch>/.ansible/collections/. That location is gitignored in the real repo,
so it survives pull-repo's `git clean -fd` between runs -- a branch is only
reinstalled when its requirements.yml is newer than the last install (tracked
via a `.installed` marker file), not on every run.

generate-playbook-commands points ANSIBLE_ROLES_PATH/ANSIBLE_COLLECTIONS_PATH
at these same directories for that branch's generated commands, so installed
dependencies are actually found at playbook-run time.

If ansible-galaxy fails for a branch, the failure (including its actual
output) is printed to stderr -- always, regardless of --verbose -- and
that branch is skipped rather than aborting the rest of the run.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def requirements_files(repo_dir):
    repo_dir = Path(repo_dir)
    if not repo_dir.is_dir():
        return
    for branch_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
        req_file = branch_dir / "requirements.yml"
        if req_file.is_file():
            yield branch_dir, req_file


def needs_install(req_file, marker):
    return not marker.is_file() or req_file.stat().st_mtime > marker.stat().st_mtime


def run_galaxy(cmd, env, verbose=False):
    if verbose:
        print(f"$ {' '.join(cmd)}", flush=True)
    try:
        subprocess.run(cmd, check=True, env=env, capture_output=not verbose, text=True)
    except subprocess.CalledProcessError as e:
        print(f"error: `{' '.join(cmd)}` failed (exit {e.returncode})", file=sys.stderr)
        if e.stdout:
            print(e.stdout.rstrip(), file=sys.stderr)
        if e.stderr:
            print(e.stderr.rstrip(), file=sys.stderr)
        return False
    return True


def install_requirements(repo_dir="repo", verbose=False):
    for branch_dir, req_file in requirements_files(repo_dir):
        ansible_dir = branch_dir / ".ansible"
        roles_path = ansible_dir / "roles"
        collections_path = ansible_dir / "collections"
        marker = ansible_dir / ".installed"

        if not needs_install(req_file, marker):
            if verbose:
                print(f"Skipping {branch_dir.name}: {req_file} unchanged since last install")
            continue

        roles_path.mkdir(parents=True, exist_ok=True)
        collections_path.mkdir(parents=True, exist_ok=True)

        role_cmd = ["ansible-galaxy", "role", "install", "-r", str(req_file), "-p", str(roles_path), "--force"]
        collection_cmd = ["ansible-galaxy", "collection", "install", "-r", str(req_file), "-p", str(collections_path), "--force"]
        env = {
            **os.environ,
            "ANSIBLE_ROLES_PATH": str(roles_path),
            "ANSIBLE_COLLECTIONS_PATH": str(collections_path),
        }

        if not run_galaxy(role_cmd, env, verbose=verbose):
            continue
        if not run_galaxy(collection_cmd, env, verbose=verbose):
            continue

        marker.touch()
        if verbose:
            print(f"Installed dependencies for {branch_dir.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--repo-dir", default="repo",
        help="Directory containing per-branch checkouts (default: %(default)s)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print install progress (failures always print, regardless of this flag)")
    args = parser.parse_args()

    install_requirements(args.repo_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
