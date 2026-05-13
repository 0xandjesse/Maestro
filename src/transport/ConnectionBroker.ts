// ============================================================
// Maestro Protocol - Connection Broker
// ============================================================
//
// Thin coordination layer that handles the network handshake
// for creating and joining Connections across different processes
// or machines.
//
// "Connection" is the network-aware primitive. Same data model,
// different transport layer.
// ============================================================

import { randomUUID } from 'crypto';
import { HttpTransport } from './HttpTransport.js';
import { LocalRegistry } from './LocalRegistry.js';
import { ConnectionManager } from '../connection/ConnectionManager.js';
import { DEFAULT_PERMISSIONS } from '../connection/ConnectionManager.js';
import { EntryMode, JoinRequest, JoinResponse, ConnectionHierarchy } from '../connection/types.js';
import { MaestroMessage } from '../types/index.js';

// ----------------------------------------------------------
// Types
// ----------------------------------------------------------

export interface ConnectionBrokerConfig {
  /** This agent's transport port - included in webhookEndpoint sent to the host. */
  localPort: number;
  /** Default: '127.0.0.1' */
  localHost?: string;
}

export interface ConnectionInvitation {
  connectionId: string;
  hostAgentId: string;
  /** http://host:port - base URL of the host's HttpTransport */
  hostEndpoint: string;
  connectionName: string;
  invitedBy: string;
}

export interface CreateConnectionResult {
  connectionId: string;
}

// ----------------------------------------------------------
// ConnectionBroker
// ----------------------------------------------------------

export class ConnectionBroker {
  constructor(
    private agentId: string,
    private transport: HttpTransport,
    private registry: LocalRegistry,
    private connectionManager: ConnectionManager,
    private config: ConnectionBrokerConfig,
  ) {}

  // ----------------------------------------------------------
  // Create a Connection (host side)
  // ----------------------------------------------------------

  /**
   * Create a new Connection locally and invite named agents.
   * Each invited agent receives a connection:invitation message via the transport.
   *
   * Returns { connectionId } - Maestro.openConnectionWith() wraps connectionId into
   * a ConnectionHandle so there is no circular import between ConnectionBroker
   * and Maestro/ConnectionHandle.
   */
  async createConnection(options: {
    name: string;
    members: string[];
    entryMode?: EntryMode;
    hierarchy?: ConnectionHierarchy;
    expiresAt?: number;
  }): Promise<CreateConnectionResult> {
    // Create the Connection locally - this agent is the host
    const connection = this.connectionManager.create(
      {
        name: options.name,
        rules: {
          entryMode: options.entryMode ?? 'open',
          memberVisibility: 'all',
          permissions: {
            lead: [...DEFAULT_PERMISSIONS.lead],
            worker: [...DEFAULT_PERMISSIONS.worker],
          },
          ...(options.hierarchy ? { hierarchy: options.hierarchy } : {}),
        },
        ...(options.expiresAt ? { expiresAt: options.expiresAt } : {}),
      },
      this.agentId,
    );

    const hostEndpoint = this.localBaseEndpoint();

    // Send connection:invitation to each invited member (best effort)
    for (const memberId of options.members) {
      const invitation: ConnectionInvitation = {
        connectionId:   connection.id,
        hostAgentId:    this.agentId,
        hostEndpoint,
        connectionName: options.name,
        invitedBy:      this.agentId,
      };

      const msg = {
        id:        randomUUID(),
        type:      'connection:invitation' as const,
        content:   `You are invited to join "${options.name}"`,
        sender:    { agentId: this.agentId },
        recipient: memberId,
        connectionId: connection.id,
        timestamp: Date.now(),
        version:   '3.2',
        payload:   invitation as unknown as Record<string, unknown>,
      };

      await this.transport.send(msg).catch((err: unknown) => {
        console.warn(`[ConnectionBroker] Failed to invite ${memberId}:`, err);
      });
    }

    return { connectionId: connection.id };
  }

  // ----------------------------------------------------------
  // Join a remote Connection (guest side)
  // ----------------------------------------------------------

  /**
   * Join a Connection hosted on another process/machine.
   * Looks up the host's base endpoint from the local registry
   * (strips /message from the registered webhookEndpoint) and
   * POSTs to POST /connections/:connectionId/join.
   */
  async joinRemote(options: {
    hostAgentId: string;
    connectionId: string;
    capabilities?: string[];
  }): Promise<JoinResponse> {
    const reg = this.registry.lookup(options.hostAgentId);
    if (!reg) {
      return { status: 'rejected', reason: 'host_not_found' };
    }

    // webhookEndpoint is "http://host:port/message" - strip path to get base
    const baseEndpoint = reg.webhookEndpoint.replace(/\/[^/]+$/, '');
    return this.joinViaEndpoint(baseEndpoint, options.connectionId, options.capabilities);
  }

  /**
   * Accept a connection:invitation by joining the remote Connection.
   * The invitation carries the host's base endpoint directly.
   */
  async acceptInvitation(invitation: ConnectionInvitation): Promise<JoinResponse> {
    return this.joinViaEndpoint(invitation.hostEndpoint, invitation.connectionId);
  }

  // ----------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------

  private async joinViaEndpoint(
    baseEndpoint: string,
    connectionId: string,
    capabilities?: string[],
  ): Promise<JoinResponse> {
    const webhookEndpoint = `${this.localBaseEndpoint()}/message`;

    const joinRequest: JoinRequest = {
      protocolVersion: '3.2',
      agentId:         this.agentId,
      identity:        {},
      webhookEndpoint,
      capabilities:    capabilities ?? [],
    };

    try {
      const res = await fetch(`${baseEndpoint}/connections/${connectionId}/join`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(joinRequest),
      });

      return (await res.json()) as JoinResponse;
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      return { status: 'rejected', reason: `network_error: ${msg}` };
    }
  }

  private localBaseEndpoint(): string {
    const host = this.config.localHost ?? '127.0.0.1';
    return `http://${host}:${this.config.localPort}`;
  }
}
