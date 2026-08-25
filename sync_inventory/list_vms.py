#!/usr/bin/env python3
"""List what each VM in a netbox-style hosts JSON file is running."""

import argparse
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--hosts-file", default="hosts.json",
        help="Path to the netbox-style hosts JSON file (default: %(default)s)",
    )
    args = parser.parse_args()

    with open(args.hosts_file) as f:
        hosts = json.load(f)

    rows = sorted((hostname, meta["role"], meta["env"]) for hostname, meta in hosts.items())

    headers = ("VM", "ROLE", "ENV")
    widths = [max(len(row[i]) for row in (headers, *rows)) for i in range(3)]

    def print_row(row):
        print("  ".join(value.ljust(width) for value, width in zip(row, widths)))

    print_row(headers)
    print_row(["-" * width for width in widths])
    for row in rows:
        print_row(row)


if __name__ == "__main__":
    main()
