// Type stubs for runtime-only OpenClaw modules
declare module 'openclaw/infra/heartbeat-wake' {
  export function requestHeartbeatNow(options: { sessionKey?: string; reason?: string }): void;
}

declare module '@maestro-protocol/core' {
  export class Maestro {
    constructor(config: any);
    start(): Promise<void>;
    stop(): Promise<void>;
    readonly peers: any[];
    readonly webhookEndpoint: string;
    onMessage(pattern: string, handler: (msg: any) => void): void;
    createOpenVenue(name: string): any;
    createHierarchicalVenue(name: string, roles: string[], chain: Record<string, string>): any;
    join(venueId: string, hostManager?: any): any;
    getVenue(venueId: string): any;
    listVenues(): any[];
    getBlackboard(venueId: string): any;
    linkBlackboard(venueId: string, blackboard: any): void;
    readonly venueManager: any;
    sendDirect(agentId: string, content: string, opts?: any): Promise<any>;
  }
}
