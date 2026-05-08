// ============================================================
// Maestro Protocol - Hermes Agent Adapter
// ============================================================
//
// Delivers inbound MaestroMessages to Hermes Agent instances
// via the Hermes API Server (OpenAI-compatible REST API).
//
// Hermes API Server must be enabled on the target host:
//   API_SERVER_ENABLED=true
//   API_SERVER_KEY=<your-key>
//   API_SERVER_PORT=8642  (default)
//
// When a Maestro message arrives for a Hermes agent, this adapter:
//   1. Formats the message as an agent prompt
//   2. POSTs to POST /v1/runs on the Hermes API server
//   3. Returns immediately (fire-and-forget by default)
//
// For request-reply patterns, set awaitResponse=true to wait for
// the run to complete and capture the output.
// ============================================================

export interface HermesAdapterConfig {
  /** Base URL of the Hermes API server, e.g. http://192.168.56.101:8642 */
  apiUrl: string;
  /** Bearer token (API_SERVER_KEY in Hermes config) */
  apiKey: string;
  /**
   * Map of Maestro agentId → Hermes session/conversation name.
   * If omitted, messages use the agentId as the conversation name.
   */
  agentSessions?: Record<string, string>;
  /**
   * If true, waits for the run to complete and returns the output.
   * Default: false (fire-and-forget).
   */
  awaitResponse?: boolean;
  /** Timeout in ms for awaited responses. Default: 90000 */
  responseTimeoutMs?: number;
  /**
   * Callback invoked when Hermes completes a run and has a response.
   * Used to route Hermes replies back as MaestroMessages to the original sender.
   */
  onResponse?: (reply: HermesReply) => void | Promise<void>;
}

export interface HermesReply {
  /** The run ID that completed */
  runId: string;
  /** The Hermes agent ID (this transport's agentId) */
  fromAgentId: string;
  /** The original sender's agentId (to route the reply back) */
  toAgentId: string;
  /** The response text from Hermes */
  output: string;
  /** The original inbound message, for context */
  originalMessage: import('../types/index.js').MaestroMessage;
}

export interface HermesRunResult {
  ok: boolean;
  runId?: string;
  output?: string;
  error?: string;
}

export class HermesAdapter {
  private config: HermesAdapterConfig;

  constructor(config: HermesAdapterConfig) {
    this.config = config;
  }

  /**
   * Wake a Hermes agent session by posting a run to the API server.
   * The MaestroMessage content is formatted into a prompt that tells
   * the Hermes agent who sent it and what the message contains.
   */
  async wakeAgent(agentId: string, message: import('../types/index.js').MaestroMessage): Promise<HermesRunResult> {
    const { apiUrl, apiKey, agentSessions, onResponse } = this.config;

    // Resolve conversation name
    const conversation = agentSessions?.[agentId] ?? agentId;

    // Format the Maestro message as a human-readable prompt
    const prompt = this.formatPrompt(message);

    try {
      const response = await fetch(`${apiUrl}/v1/runs`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({ input: prompt, conversation }),
        signal: AbortSignal.timeout(10000),
      });

      if (!response.ok) {
        const text = await response.text().catch(() => '');
        return { ok: false, error: `Hermes API error ${response.status}: ${text}` };
      }

      const data = await response.json() as { run_id?: string; status?: string };
      const runId = data.run_id;

      if (!runId) {
        return { ok: false, error: 'No run_id returned from Hermes API' };
      }

      // Always stream the response asynchronously
      // When complete, fire onResponse callback to route reply back as a MaestroMessage
      this.streamAndCallback(runId, agentId, message, onResponse).catch((err: unknown) => {
        console.error('[HermesAdapter] Stream/callback error:', err);
      });

      return { ok: true, runId };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, error: `HermesAdapter fetch error: ${msg}` };
    }
  }

  /**
   * Subscribe to SSE stream for a run and fire onResponse when complete.
   */
  private async streamAndCallback(
    runId: string,
    agentId: string,
    originalMessage: import('../types/index.js').MaestroMessage,
    onResponse?: (reply: HermesReply) => void | Promise<void>,
  ): Promise<void> {
    const result = await this.pollRunResult(runId);
    const toAgentId = originalMessage.sender.agentId;

    // Guard: never route a reply back to ourselves — this causes infinite loops.
    // Hermes should only reply to external senders (songbird, lexicon, jesse, etc.)
    if (toAgentId === agentId) {
      console.warn(`[HermesAdapter] Dropping self-reply loop: ${agentId} → ${toAgentId}`);
      return;
    }

    if (result.ok && result.output && onResponse) {
      await onResponse({
        runId,
        fromAgentId: agentId,
        toAgentId,
        output: result.output,
        originalMessage,
      });
    }
  }

  /**
   * Subscribe to SSE events stream for a run and return when it completes.
   * This is more reliable than polling since completions can happen quickly.
   */
  async pollRunResult(runId: string): Promise<HermesRunResult> {
    const { apiUrl, apiKey, responseTimeoutMs = 90000 } = this.config;

    try {
      const response = await fetch(`${apiUrl}/v1/runs/${runId}/events`, {
        headers: {
          Authorization: `Bearer ${apiKey}`,
          Accept: 'text/event-stream',
        },
        signal: AbortSignal.timeout(responseTimeoutMs),
      });

      if (!response.ok) {
        return { ok: false, runId, error: `SSE stream error ${response.status}` };
      }

      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let output = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        for (const line of chunk.split('\n')) {
          if (!line.startsWith('data:')) continue;
          try {
            const event = JSON.parse(line.slice(5).trim()) as {
              event: string;
              output?: string;
              delta?: string;
            };
            if (event.event === 'run.completed') {
              return { ok: true, runId, output: event.output };
            }
            if (event.event === 'run.failed' || event.event === 'run.cancelled') {
              return { ok: false, runId, error: `Run ${event.event}` };
            }
          } catch {
            // non-JSON line, skip
          }
        }
      }

      return { ok: true, runId, output };
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { ok: false, runId, error: `SSE stream error: ${msg}` };
    }
  }

  /**
   * Format a MaestroMessage as a readable prompt for the Hermes agent.
   * Includes sender identity, message type, and connection context.
   */
  private formatPrompt(message: import('../types/index.js').MaestroMessage): string {
    const lines: string[] = [];

    lines.push(`[Maestro Protocol — Inbound Message]`);
    lines.push(`From: ${message.sender.agentId}`);
    lines.push(`Type: ${message.type}`);

    if (message.stageId) {
      lines.push(`Connection: ${message.stageId}`);
    }

    lines.push('');
    lines.push(message.content);

    if (message.payload && Object.keys(message.payload).length > 0) {
      lines.push('');
      lines.push(`Payload: ${JSON.stringify(message.payload, null, 2)}`);
    }

    return lines.join('\n');
  }

  /**
   * Health check — returns true if the Hermes API server is reachable.
   */
  async healthCheck(): Promise<boolean> {
    try {
      const response = await fetch(`${this.config.apiUrl}/health`, {
        signal: AbortSignal.timeout(5000),
      });
      return response.ok;
    } catch {
      return false;
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}
