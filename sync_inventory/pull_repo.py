#!/usr/bin/env python3
"""Clone or update a repository with each branch checked out into its own directory under repo/.

Read-only mirror, safe to run repeatedly (e.g. via cron every 30 minutes):
  - Branch directory already exists -> git fetch + reset --hard + clean
    (discards any local edits/commits/untracked files, so the directory
    always matches origin exactly, even if someone hand-edits a file in it)
  - Branch directory doesn't exist  -> git clone

Quiet by default; pass --verbose to see routine progress and retry messages.

Usage:
    pull-repo <repo_url> [-r REPO_DIR] [-v]
"""

import argparse
import subprocess
import time
from pathlib import Path

RETRIES = 3
RETRY_DELAY = 5


def run(cmd, capture_output=False, verbose=False):
    if verbose:
        print(f"$ {' '.join(cmd)}")
    for attempt in range(1, RETRIES + 1):
        result = subprocess.run(cmd, capture_output=capture_output, text=True)
        if result.returncode == 0:
            return result
        if attempt < RETRIES:
            if verbose:
                print(f"Command failed (exit {result.returncode}), retrying in {RETRY_DELAY}s... (attempt {attempt}/{RETRIES})")
            time.sleep(RETRY_DELAY)
    raise subprocess.CalledProcessError(result.returncode, cmd)


def list_remote_branches(repo_url, verbose=False):
    result = run(["git", "ls-remote", "--heads", repo_url], capture_output=True, verbose=verbose)

    branches = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        ref = line.split("\t", 1)[1]
        branches.append(ref[len("refs/heads/"):])
    return branches


def pull_repo(repo_url, repo_dir="repo", verbose=False):
    repo_dir = Path(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    branches = list_remote_branches(repo_url, verbose=verbose)
    if not branches:
        raise SystemExit(f"No branches found in {repo_url}")

    for branch in branches:
        branch_dir = repo_dir / branch.replace("/", "_")

        if branch_dir.is_dir():
            if verbose:
                print(f"Resetting {branch} in {branch_dir} to match origin")
            run(["git", "-C", str(branch_dir), "fetch", "origin", branch], verbose=verbose)
            run(["git", "-C", str(branch_dir), "reset", "--hard", "FETCH_HEAD"], verbose=verbose)
            run(["git", "-C", str(branch_dir), "clean", "-fd"], verbose=verbose)
        else:
            if verbose:
                print(f"Cloning {branch} into {branch_dir}")
            run(["git", "clone", "--branch", branch, "--single-branch", repo_url, str(branch_dir)], verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_url", help="URL or path of the git repository to clone")
    parser.add_argument("-r", "--repo-dir", default="repo", help="Directory to hold per-branch checkouts (default: repo)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print routine progress and retry messages")
    args = parser.parse_args()

    pull_repo(args.repo_url, args.repo_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
