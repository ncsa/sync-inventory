# sync-inventory

A pipeline that turns NetBox host metadata and a multi-branch Ansible
playbook repo into ready-to-run `ansible-playbook` commands — kept in sync
automatically, safe to run on a cron.

## What it does

Each host's `role` (which playbook to run) and `env` (which git branch to
source it from) live in NetBox, embedded in the `description` field of its
IP Address entry by [nbmeta](../nbmeta). `sync-inventory` turns that into a
working Ansible setup in four steps:

1. **fetch-meta** — reads that metadata from NetBox and writes it out as
   `hosts.json`, mapping each hostname to its `env`/`role`.
2. **pull-repo** — mirrors every branch of the Ansible playbook repo into its
   own directory under `repo/<branch>/`. Existing directories are reset hard
   to match the remote (any local edits or stray files are wiped), so
   `repo/` always reflects origin exactly.
3. **generate-inventory** — groups hosts by `env` and writes one Ansible
   YAML inventory per env to `inventory/<env>.yml`, with `role` values becoming
   inventory groups.
4. **generate-playbook-commands** — for every group in every inventory,
   checks whether a matching playbook actually exists in that branch's
   checkout, and writes the valid `ansible-playbook` commands to
   `commands.sh` — one command per env/role pair, each logging to its own
   file under `logs/`.

A single host with an `env` that doesn't match any real branch, or a `role`
with no matching playbook, doesn't stop the run — it's reported (as an
`ERROR` for a missing branch, a `WARNING` for a missing playbook) and
skipped, while everything else still gets generated. A failure to reach
NetBox or the git remote is also just a warning: the pipeline falls back to
whatever `hosts.json` / `repo/` checkouts already exist on disk rather than
aborting.

`commands.sh` is generated, not run, unless you ask for it — see [Quick
guide](#quick-guide) below.

## Install

Requires Python 3.9+.

```bash
git clone <this-repo>
cd sync_inventory
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs six commands into your virtualenv: `sync-inventory`,
`fetch-meta`, `pull-repo`, `generate-inventory`, `generate-playbook-commands`,
and `list-vms`.

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

## Quick guide

Run the whole pipeline (fetch metadata, mirror branches, regenerate
inventories and commands). `-u/--repo-url` is required — there's no default:

```bash
sync-inventory -u git@example.com:org/ansible-playbooks.git
```

Also actually execute the generated `ansible-playbook` commands:

```bash
sync-inventory -u git@example.com:org/ansible-playbooks.git --run
```

Skip the NetBox fetch and use `hosts.json` as-is (e.g. while testing
locally):

```bash
sync-inventory -u git@example.com:org/ansible-playbooks.git --skip-fetch-meta
```

Point it at a different playbook repo, or override other non-default paths
(run `sync-inventory --help` for the full list):

```bash
sync-inventory --repo-url git@example.com:org/other-repo.git --logs-dir ~/ansible-logs
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
generate-inventory
generate-playbook-commands
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
