#!/usr/bin/env python3
"""Clone or update a repository with each branch checked out into its own directory under repo/.

Read-only mirror, safe to run repeatedly (e.g. via cron every 30 minutes):
  - Branch directory already exists -> git fetch + reset --hard + clean
    (discards any local edits/commits/untracked files, so the directory
    always matches origin exactly, even if someone hand-edits a file in it)
  - Branch directory doesn't exist  -> git clone

A branch name's "/" and "-" characters become "_" in its directory name
(e.g. "pttran3/SVCPLAN-1234/test" -> repo/pttran3_SVCPLAN_1234_test/), so
nested branches don't create unwanted nested directories. The actual git
operations still use the real branch name; only the local directory name
is sanitized.

Quiet by default; pass --verbose to see one line per branch ("No update to
repo/<branch>", "Updated repo/<branch>", or "Cloned repo/<branch>"). Git's
own (much noisier) output is never shown, except when a branch's update or
clone fails, where it's printed as-is (still only with --verbose) so the
actual error is visible. A branch that fails is skipped rather than
aborting the rest of the run.

Usage:
    pull-repo <repo_url> [-r REPO_DIR] [-v]
"""

import argparse
import subprocess
import time
from pathlib import Path

from sync_inventory.naming import sanitize_dir_name

RETRIES = 3
RETRY_DELAY = 5


def run(cmd, verbose=False):
    for attempt in range(1, RETRIES + 1):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result
        if attempt < RETRIES:
            if verbose:
                print(f"Command failed (exit {result.returncode}), retrying in {RETRY_DELAY}s... (attempt {attempt}/{RETRIES})")
            time.sleep(RETRY_DELAY)
    raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)


def print_git_error(action, e, verbose=False):
    if not verbose:
        return
    print(f"ERROR: {action} failed: `{' '.join(e.cmd)}` (exit {e.returncode})")
    if e.stdout:
        print(e.stdout.rstrip())
    if e.stderr:
        print(e.stderr.rstrip())


def list_remote_branches(repo_url, verbose=False):
    result = run(["git", "ls-remote", "--heads", repo_url], verbose=verbose)

    branches = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        ref = line.split("\t", 1)[1]
        branches.append(ref[len("refs/heads/"):])
    return branches


def sync_branch(repo_url, branch, branch_dir, verbose=False):
    if branch_dir.is_dir():
        try:
            before = run(["git", "-C", str(branch_dir), "rev-parse", "HEAD"], verbose=verbose).stdout.strip()
            run(["git", "-C", str(branch_dir), "fetch", "origin", branch], verbose=verbose)
            after = run(["git", "-C", str(branch_dir), "rev-parse", "FETCH_HEAD"], verbose=verbose).stdout.strip()
            run(["git", "-C", str(branch_dir), "reset", "--hard", "FETCH_HEAD"], verbose=verbose)
            run(["git", "-C", str(branch_dir), "clean", "-fd"], verbose=verbose)
        except subprocess.CalledProcessError as e:
            print_git_error(f"updating {branch_dir}", e, verbose=verbose)
            return
        if verbose:
            print(f"{'No update to' if before == after else 'Updated'} {branch_dir}")
    else:
        try:
            run(["git", "clone", "--branch", branch, "--single-branch", repo_url, str(branch_dir)], verbose=verbose)
        except subprocess.CalledProcessError as e:
            print_git_error(f"cloning {branch_dir}", e, verbose=verbose)
            return
        if verbose:
            print(f"Cloned {branch_dir}")


def pull_repo(repo_url, repo_dir="repo", verbose=False):
    repo_dir = Path(repo_dir)
    repo_dir.mkdir(parents=True, exist_ok=True)

    try:
        branches = list_remote_branches(repo_url, verbose=verbose)
    except subprocess.CalledProcessError as e:
        print_git_error(f"listing branches in {repo_url}", e, verbose=verbose)
        raise SystemExit(f"Could not list branches in {repo_url}")
    if not branches:
        raise SystemExit(f"No branches found in {repo_url}")

    for branch in branches:
        dir_name = sanitize_dir_name(branch)
        if dir_name != branch and verbose:
            print(f"Branch '{branch}' -> directory '{dir_name}'")
        branch_dir = repo_dir / dir_name
        sync_branch(repo_url, branch, branch_dir, verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_url", help="URL or path of the git repository to clone")
    parser.add_argument("-r", "--repo-dir", default="repo", help="Directory to hold per-branch checkouts (default: repo)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print one line per branch, and git's own output on error")
    args = parser.parse_args()

    pull_repo(args.repo_url, args.repo_dir, verbose=args.verbose)


if __name__ == "__main__":
    main()
