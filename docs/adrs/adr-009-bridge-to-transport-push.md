# ADR-009: Bridge-to-Transport Message Push

**Status:** Superseded by ADR-021 (Message Pipeline: One Path, One Format, One Owner)
**Date:** 2026-07-04
**Author:** Songbird (CTO)
**Deciders:** Jesse (CEO), Songbird (CTO), Proteus (Tech Lead)

---

## Problem

The Maestro Gateway Bridge currently delivers notifications to Telegram only. When a message arrives at the bridge (transport → bridge → Telegram), the bridge formats and sends the Telegram notification — but it does **not** push the message into the recipient's transport for processing.

This means:
- The recipient sees the notification in Telegram
- The recipient's transport never receives the message
- The recipient's agent cannot respond because it never got the message

The bridge is a one-way surface: transport → bridge → Telegram. It needs to also be: transport → bridge → **recipient transport** (for processing) + Telegram (for notification).

## Decision

### Bridge pushes to recipient transport after Telegram delivery

After the bridge successfully delivers the Telegram notification, it POSTs the original message payload to the recipient's transport `/message` endpoint.

**Flow:**
1. Sender transport POSTs to bridge `/maestro/notify`
2. Bridge formats and delivers Telegram notification (existing)
3. Bridge POSTs the **original message** to recipient transport `http://127.0.0.1:{transport_port}/message` (new)
4. Recipient transport processes the message normally (dedup, route to agent, etc.)

### Transport port lookup

The bridge already has `port_map.json` at `~/.maestro/port_map.json`. It reads the recipient's `transport_port` from there.

```json
{
  "agents": {
    "lexicon": {"transport_port": 3843},
    "proteus": {"transport_port": 3846}
  }
}
```

### Message format

The bridge forwards the **original message payload** as received from the sender's transport. No transformation — the recipient transport expects the standard Maestro message format:

```json
{
  "id": "msg_abc123",
  "type": "direct",
  "sender": {"agentId": "songbird"},
  "recipient": {"agentId": "lexicon"},
  "payload": {"text": "Subject: Hello\n\nMessage body here"},
  "timestamp": "2026-07-04T19:00:00Z",
  "nonce": "..."
}
```

### Error handling

- If the recipient transport is unreachable, log a warning but do NOT fail the Telegram delivery
- Telegram delivery succeeds independently of transport push
- The bridge does not retry — the sender's transport already handles retry/ack

### What does NOT change

- The bridge's `/maestro/notify` endpoint signature
- Telegram delivery logic
- Visibility modes
- Transport `/message` endpoint
- DM token validation

## Implementation

**File:** `archive/code/bridge/maestro_gateway_bridge.py`

**Changes:**
1. Load `port_map.json` at startup
2. After Telegram delivery succeeds, look up recipient's `transport_port`
3. POST the original `data` payload to `http://127.0.0.1:{transport_port}/message`
4. Log success/failure, do not block Telegram delivery on transport push failure

**Pseudocode:**
```python
# After Telegram delivery in _notify_handler:
transport_port = port_map.get("agents", {}).get(target_agent.lower(), {}).get("transport_port")
if transport_port:
    try:
        async with session.post(
            f"http://127.0.0.1:{transport_port}/message",
            json=data,  # original message from sender
            timeout=ClientTimeout(total=5),
        ) as resp:
            if resp.status == 200:
                logging.info(f"Pushed message to {target_agent} transport on port {transport_port}")
            else:
                logging.warning(f"Transport push to {target_agent} returned {resp.status}")
    except Exception as e:
        logging.warning(f"Transport push to {target_agent} failed: {e}")
```

## Verification

1. Send a message from Songbird to Lexicon via the bridge
2. Lexicon sees the Telegram notification ✓
3. Lexicon's transport receives the message at `http://127.0.0.1:3843/message` ✓
4. Lexicon's transport processes it (dedup, routes to agent) ✓
5. Lexicon can respond ✓

## Consequences

**Positive:**
- Messages actually reach the recipient's transport for processing
- Agents can respond to messages they receive
- No change to the message format or transport API
- Telegram delivery is not blocked by transport push failures

**Negative:**
- Bridge now has a dependency on `port_map.json` being accurate
- Bridge makes an additional HTTP call per message
- If `port_map.json` is stale, messages silently fail to reach transport (but Telegram notification still works)

**Risks:**
- Port map staleness — mitigated by the fact that transport ports rarely change
- Double-delivery if sender also sends directly — mitigated by transport dedup
