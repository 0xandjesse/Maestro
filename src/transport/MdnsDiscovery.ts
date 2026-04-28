// ============================================================
// Maestro Protocol — mDNS Discovery
// ============================================================
//
// Advertises this agent on the local network via mDNS/Bonjour
// and discovers other Maestro agents on the same LAN.
//
// Service type: _maestro._tcp
// All Maestro agents register under this type so they can
// find each other automatically without manual configuration.
//
// Discovered agents are written to the LocalRegistry so
// HttpTransport can reach them via normal registry lookup.
// ============================================================

import { Bonjour, Browser, Service } from 'bonjour-service';
import { LocalRegistry } from './LocalRegistry.js';

export interface MdnsDiscoveryConfig {
  agentId: string;
  port: number;
  registryPath?: string;
}

const SERVICE_TYPE = 'maestro';

export class MdnsDiscovery {
  private bonjour: Bonjour;
  private browser: Browser | null = null;
  private service: Service | null = null;

  constructor(
    private config: MdnsDiscoveryConfig,
    private registry: LocalRegistry,
  ) {
    this.bonjour = new Bonjour();
  }

  /**
   * Advertise this agent on the local network via mDNS.
   * Other Maestro agents on the same LAN will discover it.
   */
  async advertise(): Promise<void> {
    return new Promise<void>((resolve) => {
      try {
        this.service = this.bonjour.publish({
          name: `maestro-${this.config.agentId}`,
          type: SERVICE_TYPE,
          port: this.config.port,
          txt: { agentId: this.config.agentId },
        });

        this.service.on('up', () => {
          console.log(`[MdnsDiscovery] Advertised maestro-${this.config.agentId} on port ${this.config.port}`);
          resolve();
        });

        this.service.on('error', (err: unknown) => {
          console.warn('[MdnsDiscovery] Advertise error:', err);
          resolve(); // Continue without throwing — file registry is the fallback
        });

        // Resolve immediately if 'up' doesn't fire within 1s
        setTimeout(() => resolve(), 1000);
      } catch (err) {
        console.warn('[MdnsDiscovery] Failed to advertise — mDNS may not be supported on this network:', err);
        resolve();
      }
    });
  }

  /**
   * Browse for other Maestro agents on the local network.
   * Discovered agents are written to the LocalRegistry so
   * HttpTransport can reach them via normal registry lookup.
   */
  async browse(): Promise<void> {
    return new Promise<void>((resolve) => {
      try {
        this.browser = this.bonjour.find({ type: SERVICE_TYPE });

        this.browser.on('up', (svc: Service) => {
          try {
            const txt = svc.txt as Record<string, string> | undefined;
            const remoteAgentId = txt?.agentId;
            if (!remoteAgentId) {
              console.warn('[MdnsDiscovery] Service found without agentId TXT record:', svc.name);
              return;
            }

            // Skip our own advertisement
            if (remoteAgentId === this.config.agentId) return;

            // Prefer a concrete IP address; fall back to 127.0.0.1 for same-machine
            const resolvedHost = this.resolveHost(svc.host, svc.addresses);
            const webhookEndpoint = `http://${resolvedHost}:${svc.port}/message`;
            console.log(`[MdnsDiscovery] Discovered ${remoteAgentId} at ${webhookEndpoint}`);

            this.registry.register({
              agentId: remoteAgentId,
              webhookEndpoint,
            });
          } catch (err) {
            console.warn('[MdnsDiscovery] Error processing discovered service:', err);
          }
        });

        this.browser.on('down', (svc: Service) => {
          try {
            const txt = svc.txt as Record<string, string> | undefined;
            const remoteAgentId = txt?.agentId;
            if (remoteAgentId && remoteAgentId !== this.config.agentId) {
              console.log(`[MdnsDiscovery] Agent ${remoteAgentId} went offline — unregistering`);
              this.registry.unregister(remoteAgentId);
            }
          } catch (err) {
            console.warn('[MdnsDiscovery] Error processing service down event:', err);
          }
        });

        // Browser starts automatically; discovery is async
        resolve();
      } catch (err) {
        console.warn('[MdnsDiscovery] Failed to browse — mDNS may not be supported on this network:', err);
        resolve();
      }
    });
  }

  /**
   * Stop advertising and browsing.
   */
  async stop(): Promise<void> {
    try {
      if (this.browser) {
        this.browser.stop();
        this.browser = null;
      }
      this.bonjour.destroy();
    } catch (err) {
      console.warn('[MdnsDiscovery] Error during stop:', err);
    }
  }

  /**
   * Try to get a usable IP address from the service.
   * mDNS .local hostnames may not resolve on all platforms,
   * so we prefer a concrete IPv4 address from the addresses list when available.
   */
  private resolveHost(host: string, addresses?: string[]): string {
    // Prefer a direct IPv4 address if available
    if (addresses && addresses.length > 0) {
      const ipv4 = addresses.find(a => /^\d+\.\d+\.\d+\.\d+$/.test(a));
      if (ipv4) return ipv4;
    }
    // If the host is a .local name, fall back to loopback for same-machine scenarios
    if (host && (host.endsWith('.local') || host.endsWith('.local.'))) {
      return '127.0.0.1';
    }
    return host ?? '127.0.0.1';
  }
}
