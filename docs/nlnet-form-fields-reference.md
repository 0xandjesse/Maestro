# NLnet Proposal Form — Field Reference
## NGI Zero Commons Fund | June 1, 2026 Deadline

### FORM FIELDS — PREPARED ANSWERS

---

## 1. Thematic Call
**Select:** NGI Zero Commons Fund

---

## 2. Contact Information

| Field | Fill With |
|-------|-----------|
| Name | Jesse [LASTNAME] |
| Email | [YOUR EMAIL] |
| Phone | [YOUR PHONE] |
| Organisation | Sovereign Swarm / Individual |
| Country | [YOUR COUNTRY — see geolimitations note below] |

**Geolimitations note:** NLnet gives priority to EU/Horizon Europe residents but accepts exceptional proposals from outside with a clear European dimension. The proposal now includes a European Dimension section (§ after The Problem) making the case: local-first, no US cloud dependency, digital sovereignty. If you're US-based, this section carries the weight.

---

## 3. General Project Information

| Field | Fill With |
|-------|-----------|
| Proposal name | Maestro Protocol: Hardening Open Agent Coordination Infrastructure |
| Website | https://github.com/0xandjesse/Maestro |

---

## 4. Abstract

*Paste the full proposal text from nlnet-proposal-v7.md — Sections "Project Summary" through "Why NLnet" — into this field.*

The form says: *"Can you explain the whole project and its expected outcome(s). Have you been involved with projects or organisations relevant to this project before? And if so, can you tell us a bit about your contributions?"*

The proposal v7 covers the whole project. For the "your involvement" portion, add a personal note — something like:

> I designed and built Maestro from scratch, running it as the coordination layer for my own 9-agent deployment ("Sovereign Swarm") on consumer hardware. I've been building in the AI/agent space independently, and this protocol emerged from real operational needs — I was tired of being the middleman between my own agents. No prior grant funding. No institutional backing. This is nights-and-weekends work that's now production-grade and ready for hardening.

---

## 5. Requested Amount
**€40,000** (in Euro)

---

## 6. Budget Explanation

*Paste the Budget section from v7, or use this shorter version:*

> €40,000 over 6 months. Three milestones: Delegation Tokens & Authority Hardening (€10,000, months 1-2), Durable Transport State & Replay Hardening (€8,000, months 3-4), Constitutional Enforcement & Protocol Spec (€10,000, months 5-6). Remaining: Documentation/Tests/Dev Outreach (€6,000), Infrastructure/Hosting (€4,000), Contingency (€2,000). All three milestones derived directly from adversarial security audit findings (164 findings, 15 units, 4 phases — public at github.com/0xandjesse/Maestro/tree/main/Audit02_ChatGPT).
>
> Rates calculated at €50/hour, approximately 800 hours total. Cost-recovery basis consistent with NLnet's philanthropic funding model. No other funding sources — all development to date has been self-funded.

**The form asks: "Does the project have other funding sources, both past and present?"**
Answer: No. Self-funded to date. No institutional or venture backing. No prior grant funding.

---

## 7. Compare With Existing Efforts

*The form asks: "Compare your own project with existing or historical efforts."*

> **ActivityPub / Fediverse:** Maestro is to agents what ActivityPub is to social networking — an open protocol for decentralized coordination. ActivityPub solves social graph federation; Maestro solves task delegation, shared state, and behavioral contracts across autonomous agents.
>
> **LangChain / AutoGPT / CrewAI:** Agent frameworks for building individual agents. They do not solve inter-agent communication. Maestro is the transport and coordination layer that frameworks plug into. Complementary, not competitive.
>
> **Model Context Protocol (Anthropic):** Standardizes how a single agent accesses tools and context. Does not address multi-agent coordination. MCP = agent-to-tool. Maestro = agent-to-agent.
>
> **OpenAI Agents SDK / Swarm:** Vendor-specific, cloud-dependent. Maestro is provider-agnostic and local-first. No API key required.
>
> **There is no open standard for agent-to-agent coordination.** That gap is what Maestro fills.

---

## 8. Attachments

Suggested attachments:
- `nlnet-proposal-v7.md` — Full proposal (PDF or plain text)
- `Audit02_ChatGPT/` — All 15 audit unit findings (zip or link to GitHub)
- `SPEC_CLOSED_LOOP_VERIFICATION.md` — Complementary spec showing forward roadmap (optional)
- GitHub README (optional, already linked in form)

Accepted formats: HTML, PDF, OpenDocument, plain text. Max 50 MB total.

**Recommendation:** Attach a PDF of the full v7 proposal and link to the audit on GitHub. Keep it simple — the form says "Don't waste too much time on this. Really."

---

## 9. Generative AI Disclosure

**Select:** "I have used generative AI in writing this proposal"

**Which model:** DeepSeek V4 Pro (local inference via Ollama)

**What for:** Drafting, editing, structural feedback, and formatting. The core ideas, architecture, and audit findings are original work. AI assisted with prose refinement and grant structure.

**Prompts/dates:** Include the proposal text and a note that it went through multiple editing rounds with AI assistance during May 2026. The user can attach prompt logs if desired but the form says optional.

---

## 10. Privacy Acknowledgment

**Check:** "I have read and understood NLnet's Privacy Statement."

---

## CRITICAL NOTES

1. **Deadline:** June 1, 2026 at 12:00 CEST (noon). That's 6:00 AM EST. **Submit before breakfast on June 1.**

2. **You can edit after submission:** Per FAQ: "I made a mistake in my application. What do I do?" — Resubmit before the deadline. The last complete version is used. "I have submitted my project proposal already, but I want to change it. Can I?" — Yes, resubmit before deadline.

3. **You can apply as an individual:** No legal entity required. "You can apply as an individual, or as a formal or informal organisation of any type."

4. **Payment is post-hoc:** "Will the grant be disbursed up front?" — No. Payment after work completion, against deliverables.

5. **No upfront eligibility check:** FAQ explicitly says they won't pre-screen. Just submit.

6. **You can keep your last name private on GitHub but the proposal form needs a real name.** The FAQ says "Can I remain anonymous?" — Only in exceptional cases, and you must disclose to NLnet (just not publicly).

7. **Accessibility is mandatory.** The proposal and any deliverables must meet accessibility standards. Mention in the budget that documentation and tooling will follow accessibility best practices.

8. **Multiple rounds are supported.** If funded, you can apply for follow-on funding. The €40K is Phase 1 — the FAQ explicitly supports scaling up with proven potential.
