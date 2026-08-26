# sync-inventory

A pipeline that turns NetBox host metadata and a multi-branch Ansible
playbook repo into ready-to-run `ansible-playbook` commands — kept in sync
automatically, safe to run on a cron.

## What it does

Each host's `role` (which playbook to run) and `env` (which git branch to
source it from) live in NetBox, entered there via [nbmeta](../nbmeta).
`sync-inventory` turns that into a working Ansible setup, kept current
automatically:

1. **Pull the latest host assignments from NetBox.**
2. **Mirror every branch** of the Ansible playbook repo, so each environment's
   playbooks are available locally and up to date.
3. **Install each branch's dependencies** (roles and collections), so
   different branches can rely on different dependency versions without
   stepping on each other.
4. **Build an Ansible inventory per environment**, complete with that
   environment's own variables — so real settings actually apply, and two
   environments with the same group name never share values by accident.
5. **Generate the actual `ansible-playbook` commands** to run, one per
   environment/role, each fully self-contained (its own config, its own
   dependencies) so running several environments back to back never lets
   one leak into another.

The end result sitting in the project directory: a `commands/` folder with
one ready-to-run script per environment/role (e.g.
`commands/prod_a_webserver.sh`). Nothing runs automatically — `sync-inventory`
only generates these; running one (or all of them) is a separate step, with
`run-play` (see [Quick guide](#quick-guide) below).

It's built to keep working even when something's incomplete or unreachable.
A host pointed at a branch that doesn't exist, or a role with no matching
playbook, gets skipped and reported rather than stopping everything else.
Losing the connection to NetBox or the git remote just means it falls back
to whatever it already had, rather than failing outright. All of this
reporting is quiet by default — pass `-v`/`--verbose` (on `sync-inventory`
or any individual command) when you want to see it.

## Install

Requires Python 3.9+.

```bash
git clone <this-repo>
cd sync_inventory
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs eight commands into your virtualenv: `sync-inventory`,
`fetch-meta`, `pull-repo`, `install-requirements`, `generate-inventory`,
`generate-playbook-commands`, `run-play`, and `list-vms`.

### Configuration

`fetch-meta` (and therefore `sync-inventory`, unless you pass
`--skip-fetch-meta`) reads its NetBox connection details from the
environment — the same variables [nbmeta](../nbmeta) uses:

```bash
export NETBOX_URL=https://netbox.example.com
export NETBOX_TOKEN=your-api-token
export NETBOX_OWNERS=team-a,team-b
```

Without these set, `sync-inventory` still works — it just warns and reuses
whatever `hosts.json` is already on disk instead of refreshing it.

`sync-inventory`'s `-u/--repo-url` can likewise be set via `REPO_URL`
instead of passed on the command line:

```bash
export REPO_URL=git@example.com:org/ansible-playbooks.git
```

## Quick guide

Run the whole pipeline (fetch metadata, mirror branches, regenerate
inventories and commands). `-u/--repo-url` (or `REPO_URL` in the
environment) is required — there's no default:

```bash
sync-inventory -u git@example.com:org/ansible-playbooks.git
```

`sync-inventory` only (re)generates `commands/`; it never runs anything
itself. To actually execute a generated script (a real `ansible-playbook`
run), use `run-play` — one script by name, or every script under
`commands/`:

```bash
run-play -s pttran3_test_branch_proxmox
run-play --all
```

Each run is logged to its own file under `logs/`, named after the script
(e.g. `logs/pttran3_test_branch_proxmox.log`).

Target a single host instead of the script's whole group, e.g. to test one
box before rolling out to the rest:

```bash
run-play -s pttran3_test_branch_proxmox -H some-host.example.com
```

See what's available to run (the exact names `-s` accepts):

```bash
run-play --list
```

Skip the NetBox fetch and use `hosts.json` as-is (e.g. while testing
locally):

```bash
sync-inventory -u git@example.com:org/ansible-playbooks.git --skip-fetch-meta
```

Point it at a different playbook repo, or override other non-default paths
(run `sync-inventory --help` for the full list):

```bash
sync-inventory --repo-url git@example.com:org/other-repo.git --commands-dir ~/generated-commands
```

See routine progress and every warning/error as it happens (quiet by
default otherwise):

```bash
sync-inventory -u git@example.com:org/ansible-playbooks.git -v
```

See what's assigned to run where, straight from `hosts.json`:

```bash
list-vms
```

```
VM                        ROLE       ENV
------------------------  ---------  ------
vm-001.ncsa.illinois.edu  webserver  prod_a
vm-002.ncsa.illinois.edu  database   prod_a
...
```

Run an individual step on its own (each accepts `--help` for its own flags):

```bash
fetch-meta
pull-repo git@example.com:org/ansible-playbooks.git
install-requirements
generate-inventory
generate-playbook-commands
run-play -s pttran3_test_branch_proxmox
```

### Running on a schedule

`sync-inventory` refuses to start if another instance is already running
(it uses a `.sync_inventory.lock` directory in the current directory as a
lock, removed automatically on exit). That makes it safe to put on a cron
without worrying about overlapping runs:

```cron
*/30 * * * * cd /path/to/sync_inventory && .venv/bin/sync-inventory -u git@example.com:org/ansible-playbooks.git >> sync-inventory.log 2>&1
```

If a run is ever killed outright (e.g. `kill -9`), the lock can be left
behind — `sync-inventory` will tell you exactly how to clear it
(`rmdir .sync_inventory.lock`) if that happens.

## To Do

- Publish this package to a registry so it can be installed directly,
  without cloning the repository first. Still in development.
