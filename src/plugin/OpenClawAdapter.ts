// ============================================================
// Maestro Protocol — OpenClaw Adapter
// ============================================================
//
// Bridges between the HTTP transport and OpenClaw's hook system.
// When a MaestroMessage arrives for a local agent, this adapter
// POSTs to the OpenClaw hooks endpoint to wake the agent's session.
//
// Fire-and-forget: logs failures but never throws.
// ============================================================

import { MaestroMessage } from '../types/index.js';

export interface OpenClawAdapterConfig {
  /** e.g. http://127.0.0.1:18789 */
  gatewayUrl: string;
  /** OpenClaw hooks token */
  hookToken: string;
  /** Default: /hooks/agent — the isolated agent turn endpoint */
  hookPath?: string;
  /** Map agentId → sessionKey, e.g. { lex: 'agent:lex:main' } */
  agentSessions?: Record<string, string>;
  /**
   * Model to use for isolated (handoff) turns.
   * Should be a cheap non-Anthropic model — Maestro handoffs are dumb-pipe,
   * no heavy reasoning needed. e.g. 'ollama/kimi-k2.5:cloud'
   * If unset, the agent's default model is used (may incur Anthropic costs).
   */
  handoffModel?: string;
}

export class OpenClawAdapter {
  private hookUrl: string;

  constructor(private config: OpenClawAdapterConfig) {
    // POST /hooks/agent runs an isolated agent turn with a specific agentId
    const path = config.hookPath ?? '/hooks/agent';
    this.hookUrl = `${config.gatewayUrl.replace(/\/$/, '')}${path}`;
  }

  /**
   * Wake an OpenClaw agent session by injecting a message via the hooks endpoint.
   * Non-blocking — logs failures but does not throw.
   */
  async wakeAgent(agentId: string, message: MaestroMessage): Promise<void> {
    const sessionKey = this.resolveSession(agentId);
    const formattedContent = this.formatMessage(message);

    // OpenClaw POST /hooks/agent format:
    // { message, agentId, name, wakeMode, model }
    // Use handoffModel for isolated turns to avoid Anthropic token burn.
    const isHandoff = message.type === 'handoff';
    const payload: Record<string, unknown> = {
      message: formattedContent,
      agentId,
      name: `Maestro from ${message.sender.agentId}`,
      wakeMode: 'now',
    };
    if (this.config.handoffModel && isHandoff) {
      payload.model = this.config.handoffModel;
    }

    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 5000);

      const res = await fetch(this.hookUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${this.config.hookToken}`,
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });

      clearTimeout(timer);

      if (!res.ok) {
        console.warn(
          `[OpenClawAdapter] Hook rejected for ${agentId}: HTTP ${res.status}`,
        );
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`[OpenClawAdapter] Failed to wake ${agentId}: ${msg}`);
    }
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  private resolveSession(agentId: string): string {
    return this.config.agentSessions?.[agentId] ?? `agent:${agentId}:main`;
  }

  private formatMessage(message: MaestroMessage): string {
    const sender = message.sender.agentId;
    const type = message.type;
    const stage = message.stageId ? ` [connection: ${message.stageId}]` : '';

    if (message.type === 'connection:invitation') {
      const inv = (message as unknown as Record<string, unknown>)['payload'] as
        | { connectionName?: string }
        | undefined;
      return `[Maestro] Connection invitation from ${sender}: "${inv?.connectionName ?? 'unknown'}". To accept, call maestro.acceptInvitation().`;
    }

    return `[Maestro] ${type} from ${sender}${stage}: ${message.content}`;
  }
}
