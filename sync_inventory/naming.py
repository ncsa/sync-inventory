"""Shared helper for turning a git branch/env name into a single safe directory component."""


def sanitize_dir_name(name):
    """Replace characters that don't belong in a single filesystem directory component.

    Git branch names may contain "/" (used for nested branches like
    "pttran3/SVCPLAN-1234/test") and "-", neither of which we want ending up
    literally in a directory name: "/" would create unwanted nested
    directories instead of one directory per branch, and "-" is normalized
    to "_" for consistency with how role names are sanitized for Ansible
    group names.
    """
    return name.replace("/", "_").replace("-", "_")
