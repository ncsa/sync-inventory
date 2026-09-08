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
   Every role needs a matching `group_structure/<role>.yml` in that
   branch's checkout describing its group shape (see
   [Nested groups](#nested-groups) below) — a missing or invalid one is an
   error, not a silent fallback.
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
A host pointed at a branch that doesn't exist gets skipped and reported
rather than stopping everything else. Losing the connection to NetBox or
the git remote just means it falls back to whatever it already had, rather
than failing outright. All of this reporting is quiet by default — pass
`-v`/`--verbose` (on `sync-inventory` or any individual command) when you
want to see it.

Two things are deliberately *not* soft-skipped, and stop the run outright
instead: a role with a missing or invalid `group_structure/<role>.yml`
(silently falling back there could mean hosts vanish from the generated
inventory with no clear explanation), and a role assigned to an env whose
playbook file doesn't actually exist in that branch's checkout (a
role/playbook mismatch is a real misconfiguration to fix, not something to
quietly ignore).

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

### Nested groups

Every `role` needs a `group_structure/<role>.yml` file describing its
Ansible group shape — there's no automatic flat default. This file lives
in the playbook repo itself, alongside `playbooks/`, `requirements.yml`,
and `ansible.cfg` — so each branch (env) can have its own copy, same as
those. A role with no real nesting just needs a minimal file with its own
name and nothing else (e.g. `webserver:` on its own), which produces one
flat group exactly like before. A role that does want real nesting
describes the full shape, e.g. `group_structure/proxmox.yml`:

```yaml
proxmox:
proxmox_test:
  proxmox_test_one:
  proxmox_test_two:
proxmox_00:
```

There's no wrapper key — `proxmox`/`proxmox_test`/`proxmox_00` are three
independent top-level siblings (not one root per role, and their names
don't need to relate to each other). Below that top level, though, every
group name must be prefixed with its immediate parent's name
(`proxmox_test`'s children must start with `proxmox_test_`, not just
`proxmox_`) — enforced when the file is loaded. Every node becomes a real
group in the generated inventory whether or not it currently has hosts, so
`group_vars` inheritance down the tree always works.

A host lands in the node named by its NetBox `group` metadata (set via
`nbmeta --group`); with no `group` set, it falls back to the node named
after its own role — so a top-level sibling literally named after the role
(`proxmox` in the example above) is required. A missing structure file, or
one that's invalid in any way (a non-mapping top-level shape, a
naming-convention violation, a repeated group name, or missing the
required role-name group above), is a hard error rather than a silent
fallback — silently falling back could otherwise mean hosts vanish from
the generated inventory with no clear explanation. A `group` value that
doesn't match any node in the tree is dropped with a warning (`-v`) rather
than silently misplaced.

Since scripts no longer pass `--limit` by default (see above), the
matching playbook's own `hosts:` key decides which of these groups it
actually targets — e.g. `hosts: "proxmox,proxmox_00,proxmox_test"`.

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

Target a single host on top of whatever the playbook's own `hosts:` key
already targets, e.g. to test one box before rolling out to the rest:

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
