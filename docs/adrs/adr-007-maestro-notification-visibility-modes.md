# ADR-007: Maestro Notification Visibility Modes

**Status:** Superseded by ADR-021 (Message Pipeline: One Path, One Format, One Owner)
**Date:** 2026-07-04
**Author:** Jesse (CEO)
**Deciders:** Jesse (CEO), Songbird (CTO), Proteus (Tech Lead)

---

## Context

The Maestro Gateway Bridge currently surfaces transport notifications to Telegram in a single format. There is no way to control visibility — every message is fully surfaced, every time. For a mesh of 18 agents, this produces excessive Telegram noise.

Three visibility modes are needed, controlled by Telegram slash commands, with distinct formatting for sender and recipient views.

---

## Decision

### 1. Three Visibility Modes

| Command | Mode | Sender Sees | Recipient Sees |
|---------|------|-------------|----------------|
| `/maestrofull` | Full payload | Sender, recipient, full message body in code block | Sender, recipient, full message body in code block |
| `/maestroshort` | Subject only | Sender, recipient, subject line in code block | Sender, recipient, subject line in code block |
| `/maestrooff` | Silent | Nothing | Nothing |

Default: `/maestroshort`.

### 2. Format Specification

#### `/maestrofull` — Sender View

```
📤 Maestro-Out: *from* <Sender> *to* <Recipient>
```
```
<Full Message Payload>
```

#### `/maestrofull` — Recipient View

```
📨 Maestro-In *to* <Recipient> *from* <Sender>
```
```
<Full Message Payload>
```

#### `/maestroshort` — Sender View

```
📤 Maestro-Out: *from* <Sender> *to* <Recipient>
```
```
Subject: <Message Subject>
```

#### `/maestroshort` — Recipient View

```
📨 Maestro-In *to* <Recipient> *from* <Sender>
```
```
Subject: <Message Subject>
```

Only the subject line — no payload, no preview, no other content.

#### `/maestrooff`

No notification surfaced. Messages still deliver — the bridge simply does not forward to Telegram.

### 3. Emoji Convention

| Direction | Emoji | Meaning |
|-----------|-------|---------|
| Outbound | 📤 | Message leaving this agent |
| Inbound | 📨 | Message arriving at this agent |

The emoji is determined by perspective. The sender always sees 📤. The recipient always sees 📨. The bridge constructs both notifications independently — one for the sender's Telegram chat, one for the recipient's.

### 4. Code Block Formatting

Payloads and subjects are wrapped in triple-backtick code blocks (```). This visually separates the metadata line from the content and prevents Markdown parsing of message bodies.

### 5. Agent Emoji Signatures

Every agent signs Maestro messages with a unique emoji. The emoji appears at the end of the message body, inside the code block. This provides at-a-glance agent identification without color.

**Enforcement:**

1. **SOUL-level (primary):** Every agent's SOUL.md includes: "All Maestro messages MUST end with your assigned emoji on its own line inside the code block."
2. **Bridge-level (fallback):** If a message body doesn't end with the agent's registered emoji, the bridge appends it before surfacing. This catches non-compliant agents without blocking delivery.

**Emoji assignments** (`~/.maestro/agent_emojis.json`):

```json
{
  "lexicon": "💠",
  "songbird": "🐦",
  "proteus": "☠️",
  "mnemosyne": "🪬",
  "hermes-prime": "♂️",
  "lulu": "⚒️",
  "penny-lane": "🖊️",
  "stormtrooper": "⚡",
  "thoth": "📜",
  "zulu": "🪏",
  "keystone": "🏛️",
  "uatu": "👁️",
  "helper": "🤖",
  "cactus-jack": "🌵",
  "cee-lo": "🎲",
  "chatterbox": "🗣️",
  "log": "🪵",
  "mondo-gecko": "🦎"
}
```

**Example notification with emoji signature:**

```
📤 Maestro-Out: *from* lexicon *to* proteus
```
```
Status check — all transports green.

🌐
```

### 6. Slash Command Behavior

- `/maestrofull`, `/maestroshort`, and `/maestrooff` are **Telegram slash commands** — the user types them in Telegram chat.
- The Telegram bot receives the command and updates the agent's visibility mode.
- The mode is stored per-agent in `~/.maestro/bridge_visibility.json`.
- The mode persists across bridge restarts.
- The bridge reads the mode when formatting notifications for that agent.
- Changing mode takes effect immediately — no restart required.
- The commands are only available to officers (lexicon, songbird, hermes-prime, proteus, mnemosyne). Workers cannot change visibility modes.

### 7. Bridge Integration

The bridge stores the visibility mode per-agent. When a Telegram slash command arrives, the bridge updates the mode for that agent. When formatting a notification, the bridge looks up the recipient's mode and formats accordingly.

**Mode storage:** `~/.maestro/bridge_visibility.json`:
```json
{
  "lexicon": "full",
  "songbird": "short",
  "proteus": "off"
}
```

Agents not in the file default to `short`.

**Notification flow:**
1. Transport POSTs notification to bridge (unchanged — no mode field needed).
2. Bridge looks up the mode for the notification's recipient.
3. Bridge formats the notification according to the mode.
4. Bridge delivers (or suppresses, if mode is `off`).

The transport does not need to know the mode. The bridge is the single point of control.

---

## Consequences

**Positive:**
- Operators can reduce Telegram noise without losing message delivery.
- Full payload mode enables debugging without reading transport logs.
- Silent mode enables background pipeline operation with zero notification spam.
- Per-agent control means officers can run full while workers run silent.
- Code block formatting prevents Markdown injection and visually separates metadata from content.

**Negative:**
- Bridge complexity increases — three format paths instead of one.
- Slash command handling requires transport-level parsing (currently only `/shutup` and `/stfu` exist).
- Mode state must persist across restarts (new config file).

**Risks:**
- If mode state is lost on restart, agents default to short (acceptable).
- If the bridge ignores the mode field (backward compatibility), all notifications surface as full (noisy but functional).

---

## What Does NOT Change

- Message delivery. `/maestrooff` suppresses notifications, not messages.
- The bridge's health endpoint.
- The transport's `/message` endpoint.
- DM token validation.
- The `Subject:` line requirement in message content.
