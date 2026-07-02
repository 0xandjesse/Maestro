"""
Maestro secrets management CLI.

Provides `maestro secrets` subcommands for centralized secret management:
  maestro secrets list [--profile NAME]   - List all secrets (redacted)
  maestro secrets backup [--tag TAG]      - Backup current secrets.env
  maestro secrets restore [--date DATE]   - Restore from a backup
  maestro secrets sync                    - Sync from profile .env files
  maestro secrets strip [--profile NAME]  - Remove secrets from profile .env
"""

import argparse
import sys

from maestro.secrets import (
    backup_secrets,
    list_backups,
    list_secrets,
    restore_secrets,
    strip_secrets_from_profile,
    sync_from_profiles,
)


def main():
    parser = argparse.ArgumentParser(
        prog="maestro-secrets",
        description="Centralized secret management for the Maestro agent mesh",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── list ──
    list_cmd = sub.add_parser("list", help="List all secrets (values redacted)")
    list_cmd.add_argument("--profile", "-p", help="Resolve secrets for a specific profile")

    # ── backup ──
    backup_cmd = sub.add_parser("backup", help="Create a timestamped backup of secrets.env")
    backup_cmd.add_argument("--tag", "-t", help="Tag suffix for the backup filename")

    # ── restore ──
    restore_cmd = sub.add_parser("restore", help="Restore secrets from a backup")
    restore_cmd.add_argument("--date", "-d", help="Date prefix to match (e.g. 20260518)")
    restore_cmd.add_argument("--file", "-f", help="Explicit backup file path")

    # ── sync ──
    sync_cmd = sub.add_parser("sync", help="Sync secrets from profile .env files into centralized secrets.env")
    sync_cmd.add_argument("--profile", "-p", action="append", help="Profile(s) to sync (default: all)")

    # ── strip ──
    strip_cmd = sub.add_parser("strip", help="Remove secret keys from profile .env (after sync)")
    strip_cmd.add_argument("--profile", "-p", action="append", help="Profile(s) to strip")

    # ── status ──
    sub.add_parser("status", help="Show secrets.env status and backup count")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "list":
        secrets = list_secrets(profile=args.profile)
        if not secrets:
            print("No secrets found in ~/.maestro/secrets.env")
            print("Run 'maestro secrets sync' to import from profile .env files.")
        else:
            label = f" (profile: {args.profile})" if args.profile else ""
            print(f"Secrets in ~/.maestro/secrets.env{label}:")
            print()
            for key in sorted(secrets.keys()):
                print(f"  {key} = {secrets[key]}")

    elif args.command == "backup":
        path = backup_secrets(tag=args.tag)
        print(f"Backup created: {path}")
        print(f"File size: {path.stat().st_size} bytes")

    elif args.command == "restore":
        try:
            path = restore_secrets(
                date_tag=args.date,
                backup_path=args.file and __import__("pathlib").Path(args.file),
            )
            print(f"Restored secrets from backup to: {path}")
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "sync":
        profiles = args.profile  # None means all
        result = sync_from_profiles(profiles=profiles)
        if not result:
            print("No secrets found in profile .env files to sync.")
        else:
            print(f"Synced {len(result)} secret(s) to ~/.maestro/secrets.env:")
            for key in sorted(result.keys()):
                val = result[key]
                if len(val) > 12:
                    display = f"{val[:4]}...{val[-4:]}"
                else:
                    display = "***"
                print(f"  {key} = {display}")

    elif args.command == "strip":
        profiles = args.profile or []
        if not profiles:
            print("Error: --profile required for strip command", file=sys.stderr)
            sys.exit(1)
        for profile in profiles:
            removed = strip_secrets_from_profile(profile)
            if removed:
                print(f"Stripped {len(removed)} secret(s) from {profile}: {', '.join(removed)}")
            else:
                print(f"No secrets to strip from {profile}")

    elif args.command == "status":
        from maestro.secrets import SECRETS_FILE, BACKUPS_DIR
        if SECRETS_FILE.exists():
            count = len(list_secrets())
            print(f"secrets.env: {SECRETS_FILE}")
            print(f"  Keys: {count}")
            print(f"  Size: {SECRETS_FILE.stat().st_size} bytes")
            mode = oct(SECRETS_FILE.stat().st_mode & 0o777)
            print(f"  Permissions: {mode}")
        else:
            print("secrets.env: not found")
            print("  Run 'maestro secrets sync' to create from profile .env files")
        print()
        backups = list_backups()
        print(f"Backups: {len(backups)} in ~/.maestro/backups/")
        for b in backups[:5]:
            print(f"  {b['name']} ({b['size']}, {b['modified']})")


if __name__ == "__main__":
    main()