#!/usr/bin/env python3
"""Master Vault CLI — command-line interface for vault operations.

Usage:
    python vault_cli.py init                      # Generate key + create empty vault
    python vault_cli.py get-token <agent_id>      # Print decrypted token for agent
    python vault_cli.py allocate-token <agent_id>  # Draw next token from pool
    python vault_cli.py get-ports <agent_id>       # Print gateway/transport ports
    python vault_cli.py get-config <agent_id>      # Print merged config (--json for raw)
    python vault_cli.py list-agents                # List all agents with ports
    python vault_cli.py provision-token --username <bot> --token <token>
    python vault_cli.py release-token <agent_id>   # Return token to pool
    python vault_cli.py revoke-token <token_id>    # Revoke a token
    python vault_cli.py rotate-key                 # Re-encrypt vault with new key
    python vault_cli.py import-registry            # Migrate registry.json into vault
"""

import argparse
import json
import sys
import os

# Ensure vault.py is importable from same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vault import (
    MasterVault,
    VaultError,
    VaultNotFoundError,
    VaultCorruptError,
    VaultKeyError,
    TokenExhaustedError,
    _redact_token,
    VAULT_DEFAULT_PATH,
    KEY_DEFAULT_PATH,
)


def cmd_init(args):
    """Initialize vault key and create empty vault."""
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        vault.init_key()
        print(f"Key generated at {vault.key_path}")
    except VaultError as e:
        print(f"Key: {e}", file=sys.stderr)

    try:
        vault.init_vault()
        print(f"Vault created at {vault.vault_path}")
    except VaultError as e:
        print(f"Vault: {e}", file=sys.stderr)


def cmd_get_token(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        token = vault.get_token(args.agent_id)
        if args.show_full:
            print(token)
        else:
            print(_redact_token(token))
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_allocate_token(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        token = vault.allocate_token(args.agent_id)
        print(f"Allocated token {_redact_token(token)} to agent '{args.agent_id}'")
    except TokenExhaustedError:
        print("Error: No available tokens in pool", file=sys.stderr)
        sys.exit(1)
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_get_ports(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        ports = vault.get_ports(args.agent_id)
        if args.json:
            print(json.dumps(ports, indent=2))
        else:
            print(f"gateway={ports['gateway']}  transport={ports['transport']}")
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_get_config(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        config = vault.get_config(args.agent_id)
        print(json.dumps(config, indent=2))
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_list_agents(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        agents = vault.get_all_agents()
        if not agents:
            print("No agents registered.")
            return
        for agent_id in agents:
            ports = vault.get_ports(agent_id)
            token_info = vault.get_token_info(agent_id)
            token_status = token_info["id"] if token_info else "none"
            print(f"  {agent_id:15s}  gw={ports['gateway']}  tp={ports['transport']}  token={token_status}")
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_provision_token(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        token_id = vault.provision_token(args.username, args.token)
        print(f"Provisioned token {token_id} for bot '{args.username}'")
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_release_token(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        vault.release_token(args.agent_id)
        print(f"Released token from agent '{args.agent_id}'")
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_revoke_token(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        vault.revoke_token(args.token_id)
        print(f"Revoked token {args.token_id}")
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_rotate_key(args):
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    try:
        new_key_hex = args.new_key_hex if args.new_key_hex else None
        vault.rotate_master_key(new_key_hex)
        print("Vault key rotated. All data re-encrypted.")
        if args.new_key_hex:
            print("Key provided via --new-key-hex argument.")
        else:
            print("New random key generated and saved to key file.")
    except VaultError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_import_registry(args):
    """One-shot import from ~/.maestro/registry.json into vault."""
    from migrate_registry import import_registry
    vault = MasterVault(
        vault_path=args.vault_path or VAULT_DEFAULT_PATH,
        key_path=args.key_path or KEY_DEFAULT_PATH,
    )
    registry_path = args.registry_path or os.path.expanduser("~/.maestro/registry.json")
    try:
        count = import_registry(vault, registry_path)
        print(f"Imported {count} agent(s) from registry into vault.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Master Vault CLI — manage encrypted bot tokens and config",
    )
    parser.add_argument("--vault-path", help="Override vault.json path")
    parser.add_argument("--key-path", help="Override .vault_key path")

    sub = parser.add_subparsers(dest="command", required=True)

    # init
    sub.add_parser("init", help="Generate key and create empty vault")

    # get-token
    p = sub.add_parser("get-token", help="Get bot token for an agent")
    p.add_argument("agent_id")
    p.add_argument("--show-full", action="store_true", help="Show full token (default: redacted)")

    # allocate-token
    p = sub.add_parser("allocate-token", help="Draw next available token from pool")
    p.add_argument("agent_id")

    # get-ports
    p = sub.add_parser("get-ports", help="Get gateway/transport ports for an agent")
    p.add_argument("agent_id")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    # get-config
    p = sub.add_parser("get-config", help="Get merged config for an agent")
    p.add_argument("agent_id")
    p.add_argument("--json", action="store_true", help="Output as JSON")

    # list-agents
    sub.add_parser("list-agents", help="List all agents with ports and tokens")

    # provision-token
    p = sub.add_parser("provision-token", help="Add a new token to the pool")
    p.add_argument("--username", required=True, help="Bot username")
    p.add_argument("--token", required=True, help="Bot token (e.g. 123456:ABC-DEF)")

    # release-token
    p = sub.add_parser("release-token", help="Release token back to pool")
    p.add_argument("agent_id")

    # revoke-token
    p = sub.add_parser("revoke-token", help="Revoke a token permanently")
    p.add_argument("token_id")

    # rotate-key
    p = sub.add_parser("rotate-key", help="Re-encrypt vault with new key")
    p.add_argument("--new-key-hex", help="Hex-encoded 32-byte key (default: random)")

    # import-registry
    p = sub.add_parser("import-registry", help="Import registry.json into vault")
    p.add_argument("--registry-path", help="Path to registry.json (default: ~/.maestro/registry.json)")

    args = parser.parse_args()

    commands = {
        "init": cmd_init,
        "get-token": cmd_get_token,
        "allocate-token": cmd_allocate_token,
        "get-ports": cmd_get_ports,
        "get-config": cmd_get_config,
        "list-agents": cmd_list_agents,
        "provision-token": cmd_provision_token,
        "release-token": cmd_release_token,
        "revoke-token": cmd_revoke_token,
        "rotate-key": cmd_rotate_key,
        "import-registry": cmd_import_registry,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()