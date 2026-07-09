# ADR-019 — Officer Gateway Renderer

**Status:** Superseded by ADR-021 (Message Pipeline: One Path, One Format, One Owner)
**Date:** 2026-07-07
**Author:** Proteus (with Jesse)
**Depends on:** ADR-017 (Authority Originates with Actors)

---

## 1. Observation

The Telegram renderer was designed as a neutral event visualizer — it receives events from the event bus and renders them for human consumption. But this neutrality created a problem: the renderer had to infer perspective dynamically from sender/recipient/chat IDs.

This led to compensating logic:
- `same_chat` detection (are sender and recipient in the same Telegram chat?)
- Perspective switching (whose view should I render?)
- Sender/recipient suppression (don't show both copies in a shared chat)
- Chat ID comparisons

All of these exist because the renderer doesn't know who it represents.

The root cause is not "same chat," not Telegram, not bot tokens. The renderer was missing its own identity.

---

## 2. The Core Insight

> **A renderer is not a neutral event visualizer. It renders the activity stream of a single participant.**

Before today, the renderer was implicitly: "A renderer visualizes events."

After today, it's explicitly: "A renderer visualizes the activity stream of a single participant."

The invariant:

```
Every renderer has exactly one owner.
```

Once the renderer knows who it is, the direction of every message becomes deterministic:

```
if event.sender == renderer.owner:
    render_outbound(event)      # 📤 Maestro-Out: to <recipient>

elif event.recipient == renderer.owner:
    render_inbound(event)       # 📨 Maestro-In: from <sender>

else:
    ignore(event)               # Not my timeline
```

No `same_chat`. No perspective inference. No sender/recipient suppression. No chat ID comparisons. Those were all compensating for the renderer not knowing who it represented.

---

## 3. Why This Matters

### 3.1 The Split-Brain Problem

When the renderer was neutral, it tried to render events for all participants. This created a split-brain:

- From Sentinel's perspective: "I completed my job."
- From Proteus's perspective: "I got the message."
- From the human's perspective: "Nothing happened."

Three different truths, all simultaneously valid. The renderer couldn't resolve them because it had no identity to anchor on.

With an owner, the renderer renders exactly one timeline. The human sees what that officer sees. No ambiguity.

### 3.2 The Tokenized Pipeline

In a tokenized pipeline, Sentinel never surfaces anything. He produces a token. Proteus receives it and surfaces the findings. One surface path, one owner, no split-brain.

The Officer Gateway Renderer is the architectural foundation for this. When Proteus's renderer shows "📨 Maestro-In: from Sentinel," it's rendering Proteus's activity — Proteus received a token. The human sees what Proteus sees.

### 3.3 Scaling

One renderer per officer chat. Each renderer has a single configured owner. The abstraction is "one identity per rendering context," not "one process."

If Concerto wants to render Proteus's timeline in one panel and Lexicon's in another, it instantiates two renderers with different owners. The same architecture scales to Telegram, CLI, Concerto, Web UI, TUI — any rendering surface.

---

## 4. The Rendering Logic

### 4.1 Before (Neutral Event Renderer)

```
For each event:
    Format sender_text (sender's perspective)
    Format recipient_text (recipient's perspective)
    If same_chat:
        Deliver sender_text only (suppress recipient)
    Else:
        Deliver recipient_text to recipient
        Deliver sender_text to sender
```

Problems:
- Must infer perspective from chat IDs
- Must detect shared chats
- Must suppress duplicates
- Formats both perspectives even when only one is needed

### 4.2 After (Officer Gateway Renderer)

```
For each event:
    If event.sender == owner:
        Format outbound (📤 Maestro-Out: to <recipient>)
        Deliver to owner's chat
    Elif event.recipient == owner:
        Format inbound (📨 Maestro-In: from <sender>)
        Deliver to owner's chat
    Else:
        Ignore
```

No inference. No suppression. No duplicate formatting. The renderer's identity is fixed, and everything follows from that.

---

## 5. Delivery

The renderer delivers to its owner's Telegram chat. If the owner has a bot token, use it. If not, the renderer needs a fallback token to deliver through — but the header still names the correct sender and recipient. The delivery mechanism is separate from the rendering identity.

---

## 6. Relationship to ADR-017

ADR-017 established that authority originates with actors, not Grammar. Each agent owns its policies.

ADR-019 extends this to the observation layer: each renderer belongs to an actor. The renderer doesn't make policy decisions about what to show — it shows what its owner would see. The owner's identity determines the rendering, not the event's structure.

---

## 7. Consequences

### Positive
- Rendering logic becomes trivial (three branches, no inference)
- No more same_chat, perspective switching, or suppression logic
- Scales naturally to any number of rendering surfaces
- Each officer's chat shows exactly their activity stream
- Tokenized pipelines have a clear surface owner

### Negative
- Requires one renderer instance per officer chat
- Renderer must be configured with its owner identity
- Events between two non-owner agents are invisible (by design — they belong in those agents' chats)

### Neutral
- The renderer is no longer a generic component. It's an Officer Gateway Renderer. This is a conceptual simplification, not a limitation.

---

## 8. Implementation Notes

- `RENDERER_OWNER` environment variable sets the owner
- Systemd unit sets `Environment=RENDERER_OWNER=proteus`
- Fallback: if unset, renderer logs a warning and skips all events (safe default)
- The `same_chat` logic, perspective inference, and dual-formatting are removed
- Delivery always goes to the owner's configured chat
