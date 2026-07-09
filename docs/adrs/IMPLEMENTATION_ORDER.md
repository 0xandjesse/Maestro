# ADR Implementation Order

Last updated: 2026-07-07

Numbers are identifiers, not priority. This file defines the implementation sequence.
Update as dependencies shift or new ADRs land.

| Priority | ADR | Title | Depends On |
|----------|-----|-------|------------|
| 1 | 003 | Nucleus Architecture | — (foundation, approved) |
| 2 | 017 | Authority Originates with Actors | 003 |
| 3 | 018 | Policy Contexts and Normative Environments | 017 |
| 4 | 004 | Local Org as Venue Zero | 003 |
| 5 | 006 | Modular Relay Architecture | 003 |
| 6 | 010 | Visibility Surface Architecture | 003 |
| 7 | 011 | Configuration Convergence | 003 |
| 8 | 008 | Token Lifecycle Commands | 017, 018 |
| — | 005 | Agent Maintenance Audit | standalone |
| — | 012 | Remove Secondary Wake Path | standalone |
| — | 013 | Reclaim Hermes Name | standalone |
| — | 014 | Consolidate Transport Implementations | standalone |

## Dependency Graph

```
003 (Nucleus) ─── foundation, already approved
    │
    ├── 017 + 018 (Authority + Policy Contexts) ─── who owns what, how policy works
    │       │
    │       └── 008 (Token Lifecycle) ─── depends on 017/018's token model
    │
    ├── 004 (Venue Zero) ─── depends on 003's composition model
    ├── 006 (Modular Relay) ─── depends on 003
    ├── 010 (Visibility Surface) ─── depends on 003, partially implemented
    └── 011 (Configuration Convergence) ─── depends on 003

005, 012, 013, 014 ─── standalone, no architectural dependencies
```

## Pruned (superseded)

| ADR | Superseded By |
|-----|---------------|
| 004b | 006 |
| 007 | 010 |
| 009 | 010 |
| 015 | 017 |
| 016 | 017 |
