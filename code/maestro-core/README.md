# Maestro Protocol Core

The bare-minimum transport layer for the Maestro agent swarm. 16 self-contained modules, zero external dependencies beyond Python stdlib + `cryptography`.

## Architecture

```
maestro-core/
├── intent_classifier/      # M6  — Classifies message intent (work/ack/query/status)
├── registry_manager/       # M4  — Single-writer agent registry with WAL
├── port_authority/         # M10 — Port assignment and verification
├── key_authority/          # M15 — Ed25519 key management, signing, verification
├── resource_monitor/       # M7  — In-process resource checks (mem/cpu/disk)
├── task_lifecycle/         # M8  — Explicit task state machine
├── visibility_registry/    # M13 — Per-agent display mode configuration
├── message_router/         # M1  — SeenSet dedup, intent-aware routing, broadcast
├── dead_letter_queue/      # M11 — Failed message queue with TTL and retry
├── session_checkpoint/     # M12 — Agent session save/restore
├── transport_state_refresh/# M16 — Hot config reload without restart
├── dm_enforcer/            # M2  — DM policy enforcement with signed tokens
├── gate_engine/            # M3  — Workflow gates (time/dependency/resource/rate)
├── bridge_surface/         # M5  — Platform routing with visibility gating
├── config_generator/       # M9  — Template + overrides config generation
├── agent_lifecycle/        # M14 — Agent create/destroy/health/restart
└── subspecs/               # Build specifications for all 16 modules
```

## Module Format

Every module follows the same structure:

```
module_name/
├── __init__.py      # Public exports
├── interface.py     # Protocol + dataclasses (the contract)
├── schema.py        # Validation
├── <module>.py      # Implementation
└── test_<module>.py # Unit tests
```

## Test Results

**557 tests passing, 0 failures** across all 16 modules.

| Module | Tests |
|--------|-------|
| intent_classifier | 39 |
| registry_manager | 30 |
| port_authority | 12 |
| key_authority | 41 |
| resource_monitor | 19 |
| task_lifecycle | 54 |
| visibility_registry | 32 |
| message_router | 51 |
| dead_letter_queue | 27 |
| session_checkpoint | 29 |
| transport_state_refresh | 25 |
| dm_enforcer | 39 |
| gate_engine | 28 |
| bridge_surface | 39 |
| config_generator | 53 |
| agent_lifecycle | 39 |

## Dependencies

- Python 3.11+
- `cryptography` (for Ed25519 in key_authority and dm_enforcer)

## Venue Layer

This is the nucleus. Domain-specific functionality (Taskmaster, LOCR, etc.) plugs in as **venue components** that register with the core module registry. The core doesn't know about venues; venues depend on the core.

## Build Date

2026-06-30 — Extracted from `~/Projects/Maestro/runtime/` monoliths (466 files, ~368K lines).
