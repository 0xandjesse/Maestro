// ============================================================
// Maestro Protocol — Message Factory
// ============================================================

import { randomUUID } from 'crypto';
import { AgentIdentity, MaestroMessage, MessageType, ProvenanceMode } from '../types/index.js';
import { createProvenance } from '../provenance/builder.js';

export interface CreateMessageOptions {
  type?: MessageType;
  recipient?: string;
  venueId?: string;
  replyTo?: string;
  provenanceMode?: ProvenanceMode;
}

/**
 * Create a new MaestroMessage with optional provenance initialised.
 *
 * @param content       Message payload
 * @param sender        Sender identity
 * @param privateKeyHex Sender's Ed25519 private key (required if provenanceMode is set)
 * @param options       Message options
 */
export async function createMessage(
  content: string,
  sender: AgentIdentity,
  privateKeyHex?: string,
  options: CreateMessageOptions = {},
): Promise<MaestroMessage> {
  const timestamp = Date.now();
  const id = randomUUID();

  const message: MaestroMessage = {
    id,
    type: options.type ?? 'chat',
    content,
    sender,
    recipient: options.recipient ?? '*',
    timestamp,
    version: '3.2',
    ...(options.venueId ? { venueId: options.venueId } : {}),
    ...(options.replyTo ? { replyTo: options.replyTo } : {}),
  };

  if (options.provenanceMode && privateKeyHex) {
    message.provenance = await createProvenance(message, privateKeyHex, options.provenanceMode);
  }

  return message;
}
