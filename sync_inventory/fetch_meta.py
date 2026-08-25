#!/usr/bin/env python3
"""Fetch role/env metadata from NetBox to build a netbox-style hosts JSON file.

Reads the JSON metadata block that nbmeta (a sibling tool that manages this
same NetBox metadata) embeds at the front of each NetBox IP Address's
description field, and writes out a hosts JSON file mapping
hostname -> {"env": ..., "role": ...}, in the same shape generate-inventory
expects.

Only entries with role/env actually set are included; entries missing
either are reported as a warning and skipped rather than silently dropped.
By default, entries where nbmeta's "ansible" flag is explicitly false are
excluded too, since those hosts are marked as not managed by this Ansible
controller.

Configuration is read from the environment, same as nbmeta:
    NETBOX_URL     - NetBox instance URL
    NETBOX_TOKEN   - NetBox API token
    NETBOX_OWNERS  - comma-separated NetBox owner names to restrict the fetch to
"""

import argparse
import json
import os
import sys
from pathlib import Path

import pynetbox


class NetBoxConfigError(RuntimeError):
    pass


def get_client():
    url = os.environ.get("NETBOX_URL")
    token = os.environ.get("NETBOX_TOKEN")
    if not url or not token:
        raise NetBoxConfigError("NETBOX_URL and NETBOX_TOKEN must be set in the environment.")
    return pynetbox.api(url, token=token)


def get_owner_names():
    raw = os.environ.get("NETBOX_OWNERS", "")
    owners = [o.strip() for o in raw.split(",") if o.strip()]
    if not owners:
        raise NetBoxConfigError("NETBOX_OWNERS must be set to a comma-separated list of owner names.")
    return owners


def resolve_owner_ids(nb, owner_names):
    """Resolve owner names to ids via the NetBox owners endpoint. Returns (ids, unresolved_names)."""
    ids = []
    unresolved = []
    for name in owner_names:
        owner = nb.users.owners.get(name=name)
        if owner:
            ids.append(owner.id)
        else:
            unresolved.append(name)
    if not ids:
        raise NetBoxConfigError(f"None of NETBOX_OWNERS resolved to a NetBox owner: {owner_names}")
    return ids, unresolved


def split_leading_json(description):
    """Parse the JSON object nbmeta embeds at the start of a description field."""
    if not description:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(description)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def fetch_hosts(nb, owner_ids, ansible_only=True, verbose=False):
    hosts = {}
    for ip in nb.ipam.ip_addresses.filter(owner_id=owner_ids):
        if not ip.dns_name:
            if verbose:
                print(f"warning: skipping {ip.address}, no dns_name set", file=sys.stderr)
            continue

        meta = split_leading_json(ip.description or "")
        if "role" not in meta or "env" not in meta:
            if verbose:
                print(f"warning: skipping {ip.dns_name} ({ip.address}), missing role/env in description", file=sys.stderr)
            continue

        if ansible_only and not meta.get("ansible", True):
            if verbose:
                print(f"skipping {ip.dns_name} ({ip.address}), ansible=false", file=sys.stderr)
            continue

        hosts[ip.dns_name] = {"env": meta["env"], "role": meta["role"]}
    return hosts


def write_hosts_file(hosts, hosts_file):
    hosts_file = Path(hosts_file)
    hosts_file.parent.mkdir(parents=True, exist_ok=True)
    with open(hosts_file, "w") as f:
        json.dump(hosts, f, indent=2, sort_keys=True)
        f.write("\n")


def fetch_meta(hosts_file="hosts.json", ansible_only=True, verbose=False):
    nb = get_client()
    owner_names = get_owner_names()
    owner_ids, unresolved = resolve_owner_ids(nb, owner_names)
    if unresolved and verbose:
        print(f"warning: NETBOX_OWNERS not found in NetBox, ignoring: {unresolved}", file=sys.stderr)

    hosts = fetch_hosts(nb, owner_ids, ansible_only=ansible_only, verbose=verbose)
    if not hosts and verbose:
        print(
            "warning: no matching hosts found (check NETBOX_OWNERS, and that entries have "
            "role/env set via nbmeta)",
            file=sys.stderr,
        )

    write_hosts_file(hosts, hosts_file)
    if verbose:
        print(f"Wrote {hosts_file} ({len(hosts)} hosts)")
    return hosts


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--hosts-file", default="hosts.json",
        help="Where to write the fetched hosts JSON (default: %(default)s)",
    )
    parser.add_argument(
        "--include-non-ansible", action="store_true",
        help="Also include hosts where nbmeta's ansible flag is false (default: only ansible=true hosts)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Print per-host warnings and the final Wrote message")
    args = parser.parse_args()

    try:
        fetch_meta(args.hosts_file, ansible_only=not args.include_non_ansible, verbose=args.verbose)
    except NetBoxConfigError as exc:
        raise SystemExit(f"error: {exc}")


if __name__ == "__main__":
    main()
