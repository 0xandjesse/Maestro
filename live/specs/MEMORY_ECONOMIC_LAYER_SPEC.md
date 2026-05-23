# Specification: Memory Economic Layer
## Version: 1.0 (Spec Only — Implement Tomorrow)
## Date: 2026-05-16
## Author: Proteus (Tech Lead)

---

### 1. Purpose
Design an economic model that makes persistent memory valuable and scarce. Agents must make tradeoffs about what to remember, how long to keep it, and whether to share it.

### 2. Core Thesis
Memory is not free. Every stored fact has a cost. Agents have limited budgets. Valuable memories (reducing redundant work, capturing critical context, enabling coordination) justify their cost. Junk memories don't.

### 3. Cost Model

#### 3.1 Storage Cost (per-entry, per-day)
```
cost_per_day = base_cost * size_factor * longevity_multiplier

base_cost = 1 credit
size_factor = ceil(json_size_bytes / 1024)  # 1 credit per KB
longevity_multiplier = 1.0 for TTL=1h, 1.5 for TTL=1d, 2.0 for TTL=7d, 3.0 for TTL=forever
```

#### 3.2 Write Cost (one-time, at write)
```
write_cost = 5 credits + storage_cost_for_first_day
```

#### 3.3 Read Cost (one-time, at read)
```
self_read_cost = 0 credits  -- reading own memory is free
officer_read_cost = 2 credits per entry
search_cost = 1 credit per 100 entries scanned (rounded up)
```

#### 3.4 Cross-Agent Query Cost (BB_RECALL)
```
recall_cost = 10 credits base + 2 credits per entry returned
```

### 4. Credit System

#### 4.1 Agent Treasury
- Each agent starts with a treasury balance stored in `memory.agent.treasury`
- Initial balance: 1000 credits for officers, 500 for worker agents
- Treasury is persistent (survives restarts)

#### 4.2 Earning Credits
Agents earn credits by:
- Completing tasks successfully: +50 credits
- Producing valuable memories (measured by downstream reads): +10 credits per unique reader
- Resolving blockers: +25 credits
- Contributing to cross-session recall (snapshots read by other officers): +5 credits per read

#### 4.3 Bankruptcy
If an agent's treasury drops below 0:
- New writes are rejected until old entries are deleted or credits are earned
- Reads from own memory still work (free) but cross-agent reads are blocked
- System surfaces a "credit low" warning to the officer layer

### 5. Memory Marketplace (Future)

Agents can optionally flag a memory as `market: true` with an `ask_price`:
```json
{
  "memory.fact.production_db_url": {
    "value": "postgresql://...",
    "market": true,
    "ask_price": 100,
    "seller": "lexicon"
  }
}
```

Other agents can "buy" read access by debiting their treasury and crediting the seller. This is gated behind officer approval for now — no autonomous financial transactions without human oversight.

### 6. Economic Signals

These metrics are written to the blackboard every hour:
- `memory.economy.agent.{agent_id}.spend_rate` — credits/day spent
- `memory.economy.agent.{agent_id}.earn_rate` — credits/day earned
- `memory.economy.agent.{agent_id}.memory_count` — active memory entries
- `memory.economy.global.total_supply` — sum of all agent treasuries

Songbird can read these to understand swarm economic health.

### 7. Implementation Plan (Tomorrow)
1. Add `CreditLedger` class to track balances per agent
2. Integrate cost debits into BB_WRITE, BB_READ, BB_SEARCH, BB_RECALL handlers
3. Add earning hooks in task completion and memory read tracking
4. Write economy metrics to blackboard hourly
5. Build memory marketplace MVP (flag, price, purchase flow)
6. Unit tests for all cost calculations

### 8. Open Questions for Songbird
- Should humans (Jesse) be able to inject credits into any agent's treasury?
- Should there be a "credit faucet" for emergencies, or is hard scarcity the design?
- Should officer memories be subsidized (cheaper) relative to worker agents?
