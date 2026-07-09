#!/usr/bin/env python3
"""Maestro Deployment Authority — ADR-003.

Runs the full deployment pipeline:
  1. Verify port map consistency (no conflicts, all agents registered)
  2. Regenerate all agent configs from canonical port map
  3. Generate systemd unit files
  4. Verify running ports match port map

Usage:
    python3 deploy.py              # Full deployment
    python3 deploy.py --dry-run    # Show what would change
    python3 deploy.py --verify     # Verify only, no changes
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────
NUCLEUS_DIR = Path(__file__).resolve().parent
MAESTRO_HOME = Path.home() / ".maestro"
PORT_MAP_PATH = MAESTRO_HOME / "port_map.json"
REGISTRY_PATH = MAESTRO_HOME / "registry.json"
CONFIGS_DIR = MAESTRO_HOME / "configs"
UNITS_DIR = Path.home() / ".config" / "systemd" / "user"

sys.path.insert(0, str(NUCLEUS_DIR.parent))
from nucleus.modules.port_authority import FilePortAuthority
from nucleus.modules.config_generator import FileConfigGenerator


def main() -> None:
    parser = argparse.ArgumentParser(description="Maestro Deployment Authority")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change")
    parser.add_argument("--verify", action="store_true", help="Verify only, no changes")
    args = parser.parse_args()

    dry_run = args.dry_run
    verify_only = args.verify

    print("=" * 60)
    print("Maestro Deployment Authority — ADR-003")
    print("=" * 60)

    # ── Step 1: Load Port Authority ─────────────────────────────────────
    print("\n[1/4] Loading Port Authority...")
    pa = FilePortAuthority(str(PORT_MAP_PATH))
    agents = pa.list_all()
    print(f"  {len(agents)} agents in port map")

    # ── Step 2: Verify port map ─────────────────────────────────────────
    print("\n[2/4] Verifying port assignments...")
    ok, errors = pa.verify()
    if errors:
        print(f"  ⚠ {len(errors)} port mismatches:")
        for e in errors:
            print(f"    - {e}")
    else:
        print("  ✓ All ports verified")

    if verify_only:
        sys.exit(0 if ok else 1)

    # ── Step 3: Regenerate configs ──────────────────────────────────────
    print("\n[3/4] Regenerating agent configs...")
    gen = FileConfigGenerator(
        port_map_path=str(PORT_MAP_PATH),
        registry_path=str(REGISTRY_PATH),
        configs_dir=str(CONFIGS_DIR),
    )

    if dry_run:
        results = gen.regenerate_all()
        for agent_id, config in sorted(results.items()):
            print(f"  would write {agent_id}: port={config.port} api={config.hermesApiUrl}")
        print(f"  {len(results)} configs would be regenerated")
    else:
        results = gen.regenerate_all()
        for agent_id, config in sorted(results.items()):
            path = gen.write(agent_id, config)
            issues = gen.validate(config)
            status = "✓" if not issues else f"⚠ {issues}"
            print(f"  {status} {agent_id}: port={config.port} api={config.hermesApiUrl}")
        print(f"  {len(results)} configs regenerated")

    # ── Step 4: Generate systemd units ──────────────────────────────────
    print("\n[4/4] Generating systemd units...")
    if dry_run:
        print(f"  would generate {len(agents) * 2} unit files")
    else:
        unit_results = pa.generate_units()
        print(f"  {sum(len(v) for v in unit_results.values())} unit files generated")
        print("  Run 'systemctl --user daemon-reload' to pick up changes")

    print("\n" + "=" * 60)
    if dry_run:
        print("DRY RUN COMPLETE — no changes made")
    else:
        print("DEPLOYMENT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
