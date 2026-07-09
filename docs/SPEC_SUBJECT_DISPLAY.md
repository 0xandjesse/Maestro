# Subject Field + Short/Long Display — Specification

**Status:** Ready for implementation
**Context:** `/maestrolong` and `/maestroshort` slash commands already work (gateway patch stores `display_mode` in `maestro_visibility.json`), but the bridge never reads it and no `subject` field exists on messages.
**Target:** `maestro_transport.py` + `maestro_gateway_bridge.py`
**Implementer:** Proteus

---

## Overview

Add a mandatory `subject` field to all Maestro P2P messages (like an email subject line). Make the gateway bridge honor `display_mode` from `maestro_visibility.json`:

- **`/maestroshort`**: Show header + subject ONLY (not the body)
- **`/maestrolong`**: Show header + subject + full body (current behavior)
- **`/maestrooff`**: Suppress all (already works)

---

## 1. Transport: Add `subject` to outbound messages

### 1.1 LLM-generated subjects

In `_process_message()`, after `output = await self.hermes.send_and_complete(message)` and before building the reply dict, extract a subject from the LLM output.

**Simple extractor:** Take the first sentence up to 80 chars. If the output starts with a greeting ("Acknowledged", "Copy", "Got it", "Understood", etc.), use that as the subject.

```python
import re

def extract_subject(output: str, max_len: int = 80) -> str:
    """Extract a subject line from LLM output."""
    if not output:
        return "(no content)"
    # Take first sentence (split on ., !, ?, or newline)
    first = re.split(r'[\.\!\?\n]', output.strip())[0].strip()
    if len(first) > max_len:
        first = first[:max_len-3] + "..."
    return first or output[:max_len]
```

### 1.2 Add `subject` to the reply dict (line ~1152)

```python
reply = {
    "id": str(uuid.uuid4()),
    "type": "direct",
    "content": output,
    "subject": extract_subject(output),
    "sender": {"agentId": self.agent_id},
    ...
}
```

### 1.3 Add `subject` to bridge payloads

Two places surface messages to the bridge:

**`_surface_to_gateway()` (line ~1412):**
```python
payload = {
    "agent_id": self.agent_id,
    "from": sender,
    "to": message.get("recipient", ""),
    "subject": message.get("subject", extract_subject(content)),
    "content": content,
    ...
}
```

**Outbound mirror in `_process_message()` (line ~1138):**
```python
mirror_payload = {
    "agent_id": profile,
    "from": profile,
    "to": sender_id,
    "subject": extract_subject(output),
    "content": output,
    ...
}
```

---

## 2. Bridge: Read `display_mode` and format accordingly

### 2.1 Load visibility state

Add a function to read `maestro_visibility.json`:

```python
VISIBILITY_PATH = HERMES_HOME / "maestro_visibility.json"

def _get_display_mode(agent_id: str) -> str:
    """Return 'long' (default), 'short', or 'off' for an agent."""
    if not VISIBILITY_PATH.exists():
        return "long"
    try:
        data = json.loads(VISIBILITY_PATH.read_text())
        if isinstance(data, dict) and agent_id in data:
            return data[agent_id].get("display_mode", "long")
    except Exception:
        pass
    return "long"
```

### 2.2 Short mode formatting

In `_send_notification()`, before building `full_text`, check display mode:

```python
display_mode = _get_display_mode(to_agent_id)
subject = data.get("subject", "")

if display_mode == "off":
    return True, "suppressed"  # Don't send anything

if display_mode == "short":
    # Short mode: header + subject only, no body
    short_text = header + (subject or body[:80])
    # ... send short_text, no file attachment
    return ...

# Long mode (default): header + subject + body (current behavior)
full_text = header + body  # body already contains subject as first line via LLM output
# ... existing logic
```

### 2.3 Short mode header

For short mode, make the header compact:
```
📨 proteus → lexicon: "Deploying Nginx on staging server"
```

Instead of the current verbose:
```
📨 Maestro direct from proteus:

Deploying Nginx on staging server — confirmed build passes all tests and health checks return 200.
```

---

## 3. Subject extraction for initial messages

For the FIRST message in a conversation (not a reply), the sender's LLM generates the content. The transport extracts the subject from that content. The receiving transport gets the `subject` field in the message envelope and forwards it to the bridge.

**Key rule:** `subject` is set by the ORIGINATING agent's transport. Receivers pass it through unchanged. If a message arrives without a `subject` (legacy), the receiver extracts one from `content`.

---

## 4. Files to modify

| File | Changes |
|------|---------|
| `runtime/maestro_transport.py` | Add `extract_subject()`, add `subject` to reply dict and both bridge payloads |
| `runtime/maestro_gateway_bridge.py` | Add `_get_display_mode()`, modify `_send_notification()` for short/long/off modes, pass `subject` from data |

---

## 5. Hard Boundaries

1. **Do not touch the gateway patch files.** The `/maestrolong` and `/maestroshort` slash commands already work.
2. **Do not modify any agent `.env` files.** The visibility state lives in `maestro_visibility.json`.
3. **Do not touch GitHub.**
4. **Test with at least two agents** — send a message between proteus and lexicon in short mode, verify only subject displays.
5. **Report results and STOP.**

---

## 6. Verification Checklist

- [ ] `extract_subject()` correctly extracts first sentence from LLM output
- [ ] Outbound P2P messages carry a `subject` field
- [ ] Bridge payloads carry `subject` field
- [ ] Bridge reads `display_mode` from `maestro_visibility.json`
- [ ] `/maestroshort`: only header + subject displayed, no body
- [ ] `/maestrolong`: header + subject + full body displayed (current behavior)
- [ ] `/maestrooff`: nothing displayed
- [ ] Subject survives P2P relay (originating agent sets it, receiver passes it through)
