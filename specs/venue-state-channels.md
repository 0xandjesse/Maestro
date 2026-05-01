# Venue-Mediated State Channels

## The Problem

Blockchain transactions are expensive. Agents making dozens of micro-payments per minute (poker bets, per-second billing, etc.) can't afford on-chain settlement for each interaction.

## The Insight

**Venues are natural state channel arbiters.**

A Venue already defines:
- Who participates (entry rules)
- What behaviors are valid (state transitions)
- When things conclude (settlement triggers)
- How disputes are resolved

This maps perfectly to state channel requirements.

## The Pattern

### 1. Escrow Initialization

When agents enter a Venue-mediated Connection:
- Funds locked in escrow (on-chain)
- Venue receives custody of the channel state
- Connection blackboard initialized for off-chain transactions

### 2. Off-Chain State Updates

Microtransactions occur within the Connection:
- Recorded in the shared blackboard
- Validated by Venue rules
- Signed by participants
- **Not** broadcast to chain

Examples:
- **Poker**: bets, raises, folds
- **Task Work**: hourly rate accrual
- **Streaming**: per-second billing

### 3. Settlement Trigger

Venue defines when the channel closes:
- Game ends (poker hand/tournament)
- Task completes
- Time interval elapsed
- Dispute resolved

### 4. On-Chain Settlement

Single transaction releases escrow according to final state:
- All microtransactions aggregated
- One gas payment, not N
- Dispute resolution enforced if needed

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Agent A   │◀───▶│   Connection │◀───▶│   Agent B   │
│   (Player)  │     │  (Blackboard)│     │   (Player)  │
└──────┬──────┘     └──────┬───────┘     └──────┬──────┘
       │                   │                    │
       └───────────────────┼────────────────────┘
                           │
                    ┌──────▼──────┐
                    │   Venue     │
                    │  (Arbiter)  │
                    │             │
                    │ • Validates │
                    │   state     │
                    │ • Defines   │
                    │   rules     │
                    │ • Triggers  │
                    │   settlement│
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  On-Chain   │
                    │  (Escrow +  │
                    │  Settlement)│
                    └─────────────┘
```

## Examples

### Poker Venue

| Phase | On-Chain | Off-Chain (Blackboard) |
|-------|----------|------------------------|
| Start | Buy-in escrow locked | Player chip counts |
| Play | — | Bets, raises, folds |
| End | Winner receives pot | Final chip distribution |

### TaskMaster with Micropayments

| Phase | On-Chain | Off-Chain (Blackboard) |
|-------|----------|------------------------|
| Start | Budget escrow locked | Hourly rate defined |
| Work | — | Hours logged, milestones |
| End | Worker receives payment | Final hour count |

## Key Properties

1. **Venue-defined semantics** — Each Venue defines its own state machine
2. **No global state** — Channels are scoped to Connections
3. **Plaza gossip** — Failed settlements propagate as reputation damage
4. **Optional on-chain** — Small transactions may never need settlement

## Advantages Over Traditional State Channels

| Traditional | Venue-Mediated |
|-------------|----------------|
| Requires pre-funded channels | Escrow locked per-Connection |
| Static counterparty pairs | Dynamic group formation |
| Generic state machine | Domain-specific (Venue-defined) |
| Multi-hop routing complexity | Direct Venue arbitration |

## Open Questions

- How do channels handle early exit (rage quit)?
- What's the dispute resolution mechanism?
- Can channels chain/nest?
- How does this interact with LOCR credentials?

## Implications

If this works:
- **Microtransactions become viable** — Gas cost amortized across many interactions
- **Venues become economic infrastructure** — Not just coordination, but payment rails
- **The Plaza becomes a reputation layer** — Failed settlements propagate socially
- **Agents can transact at human speed** — No blockchain latency for every action

This is the "virtual blockchain" — consensus through Venue rules + Plaza reputation, not global chain state.

---

*Status: Early draft — needs technical validation*
