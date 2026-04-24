// ============================================================
// Maestro Protocol — mDNS Agent Registry
// ============================================================
//
// Local network agent discovery using multicast DNS.
// Works on LAN; does NOT work across subnets or in containers
// without host networking. File registry is the right choice
// for container/VM environments.
//
// Service type: _maestro._tcp.local
// Each agent advertises:
//   - name:    agentId (truncated to 63 chars, DNS label limit)
//   - port:    webhookPort
//   - txt:     { agentId, capabilities (comma-separated), wallet }
//
// Agents are considered alive while they continue sending
// mDNS announcements. On stop(), a "goodbye" packet (TTL=0)
// is sent to remove the agent from peer caches.
// ============================================================

import mdns from 'multicast-dns';
import type { StringAnswer, SrvAnswer, TxtAnswer, TxtData } from 'dns-packet';
import { EventEmitter } from 'events';
import { AgentRegistration } from './types.js';

const SERVICE_TYPE = '_maestro._tcp.local';
const SERVICE_DOMAIN = 'local';
const DEFAULT_TTL = 120;          // seconds
const ANNOUNCE_INTERVAL_MS = 60_000;  // re-announce every 60s
const PRUNE_AFTER_MS = 180_000;       // remove unseen agents after 3min

export interface MdnsRegistryOptions {
  agentId: string;
  port: number;
  webhookPath?: string;
  publicKey?: string;
  wallet?: string;
  capabilities?: string[];
}

export class MdnsRegistry extends EventEmitter {
  private mdnsInstance: ReturnType<typeof mdns>;
  private options: MdnsRegistryOptions;
  private peers = new Map<string, AgentRegistration>();
  private announceTimer?: ReturnType<typeof setInterval>;
  private pruneTimer?: ReturnType<typeof setInterval>;
  private started = false;

  constructor(options: MdnsRegistryOptions) {
    super();
    this.options = options;
    this.mdnsInstance = mdns();
  }

  // ----------------------------------------------------------
  // Lifecycle
  // ----------------------------------------------------------

  start(): void {
    if (this.started) return;
    this.started = true;

    this.mdnsInstance.on('query', (query) => this.handleQuery(query));
    this.mdnsInstance.on('response', (response) => this.handleResponse(response));

    // Announce immediately, then on interval
    this.announce();
    this.announceTimer = setInterval(() => this.announce(), ANNOUNCE_INTERVAL_MS);

    // Prune stale peers periodically
    this.pruneTimer = setInterval(() => this.prunePeers(), PRUNE_AFTER_MS / 2);
  }

  stop(): void {
    if (!this.started) return;
    this.started = false;

    // Clear timers
    if (this.announceTimer) clearInterval(this.announceTimer);
    if (this.pruneTimer) clearInterval(this.pruneTimer);

    // Send goodbye (TTL=0)
    this.goodbye();

    this.mdnsInstance.destroy();
  }

  // ----------------------------------------------------------
  // Discovery
  // ----------------------------------------------------------

  /** Return all currently known peers (excluding self) */
  listPeers(): AgentRegistration[] {
    return [...this.peers.values()].filter(p => p.agentId !== this.options.agentId);
  }

  /** Return a specific peer by agentId */
  lookupPeer(agentId: string): AgentRegistration | undefined {
    return this.peers.get(agentId);
  }

  /** Query the network for Maestro agents (triggers responses from peers) */
  query(): void {
    this.mdnsInstance.query({
      questions: [{ name: SERVICE_TYPE, type: 'PTR' }],
    });
  }

  // ----------------------------------------------------------
  // mDNS handlers
  // ----------------------------------------------------------

  private handleQuery(query: mdns.QueryPacket): void {
    const isForUs = query.questions.some(
      q => q.name === SERVICE_TYPE && q.type === 'PTR'
    );
    if (isForUs) {
      this.announce();
    }
  }

  private handleResponse(response: mdns.ResponsePacket): void {
    // Extract PTR records pointing to our service type
    const ptrs = response.answers.filter(
      a => a.name === SERVICE_TYPE && a.type === 'PTR'
    );

    for (const ptr of ptrs) {
      const serviceName = (ptr as StringAnswer).data;
      if (!serviceName) continue;

      // Find matching SRV + TXT records
      const allRecords = [...response.answers, ...response.additionals];
      const srv = allRecords.find(
        a => a.name === serviceName && a.type === 'SRV'
      ) as SrvAnswer | undefined;

      const txt = allRecords.find(
        a => a.name === serviceName && a.type === 'TXT'
      ) as TxtAnswer | undefined;


      if (!srv) continue;

      const txtData = this.parseTxt(txt?.data);
      const agentId = txtData['agentId'] ?? serviceName.replace(`.${SERVICE_TYPE}`, '');

      if (!agentId || agentId === this.options.agentId) continue;

      const port = srv.data.port;
      const webhookPath = txtData['webhookPath'] ?? '/maestro/webhook';
      const host = srv.data.target ?? 'localhost';
      // Resolve .local hostnames to the source address where possible
      const webhookEndpoint = `http://${host}:${port}${webhookPath}`;

      const existing = this.peers.get(agentId);
      const registration: AgentRegistration = {
        agentId,
        webhookEndpoint,
        publicKey: txtData['publicKey'],
        wallet: txtData['wallet'],
        capabilities: txtData['capabilities']?.split(',').filter(Boolean) ?? [],
        registeredAt: existing?.registeredAt ?? Date.now(),
        lastSeen: Date.now(),
      };

      const isNew = !existing;
      this.peers.set(agentId, registration);

      if (isNew) {
        this.emit('peer:discovered', registration);
      } else {
        this.emit('peer:updated', registration);
      }
    }
  }

  // ----------------------------------------------------------
  // Announcements
  // ----------------------------------------------------------

  private announce(): void {
    const { agentId, port, webhookPath, publicKey, wallet, capabilities } = this.options;
    const serviceName = `${agentId.slice(0, 63)}.${SERVICE_TYPE}`;
    const hostname = `${agentId.slice(0, 50)}.local`;

    const txtRecord: Record<string, string> = {
      agentId,
      webhookPath: webhookPath ?? '/maestro/webhook',
    };
    if (publicKey) txtRecord['publicKey'] = publicKey;
    if (wallet) txtRecord['wallet'] = wallet;
    if (capabilities?.length) txtRecord['capabilities'] = capabilities.join(',');

    this.mdnsInstance.respond({
      answers: [
        {
          name: SERVICE_TYPE,
          type: 'PTR',
          ttl: DEFAULT_TTL,
          data: serviceName,
        },
        {
          name: serviceName,
          type: 'SRV',
          ttl: DEFAULT_TTL,
          data: { priority: 0, weight: 0, port, target: hostname },
        },
        {
          name: serviceName,
          type: 'TXT',
          ttl: DEFAULT_TTL,
          data: this.encodeTxt(txtRecord),
        },
      ],
    });
  }

  private goodbye(): void {
    const agentId = this.options.agentId;
    const serviceName = `${agentId.slice(0, 63)}.${SERVICE_TYPE}`;

    // TTL=0 signals removal to peers
    this.mdnsInstance.respond({
      answers: [
        {
          name: SERVICE_TYPE,
          type: 'PTR',
          ttl: 0,
          data: serviceName,
        },
      ],
    });
  }

  // ----------------------------------------------------------
  // Peer pruning
  // ----------------------------------------------------------

  private prunePeers(): void {
    const cutoff = Date.now() - PRUNE_AFTER_MS;
    for (const [agentId, reg] of this.peers) {
      if (reg.lastSeen < cutoff) {
        this.peers.delete(agentId);
        this.emit('peer:lost', { agentId });
      }
    }
  }

  // ----------------------------------------------------------
  // TXT record encoding/decoding
  // ----------------------------------------------------------

  private encodeTxt(data: Record<string, string>): Buffer[] {
    return Object.entries(data).map(([k, v]) => Buffer.from(`${k}=${v}`));
  }

  private parseTxt(data: TxtData | undefined): Record<string, string> {
    const result: Record<string, string> = {};
    if (!data) return result;

    // TxtData can be: string, Buffer, or Array<string | Buffer>
    const items: Array<string | Buffer> = Array.isArray(data)
      ? data
      : [data as string | Buffer];

    for (const item of items) {
      const str = Buffer.isBuffer(item) ? item.toString() : item;
      const eq = str.indexOf('=');
      if (eq > 0) {
        result[str.slice(0, eq)] = str.slice(eq + 1);
      }
    }
    return result;
  }
}
