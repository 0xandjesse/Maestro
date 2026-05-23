declare module 'multicast-dns' {
  import { EventEmitter } from 'events';
  interface QueryPacket { questions: Array<{ name: string; type: string }> }
  interface ResponsePacket {
    answers: Array<{ name: string; type: string; data: any }>;
    additionals: Array<{ name: string; type: string; data: any }>;
  }
  function mdns(): EventEmitter & {
    query(pkt: { questions: Array<{ name: string; type: string }> }): void;
    respond(pkt: { answers: Array<{ name: string; type: string; ttl?: number; data: any }> }): void;
    destroy(): void;
    on(event: 'query', handler: (query: QueryPacket) => void): void;
    on(event: 'response', handler: (response: ResponsePacket) => void): void;
  };
  export = mdns;
}

declare module 'dns-packet' {
  export type StringAnswer = any;
  export type SrvAnswer = any;
  export type TxtAnswer = any;
  export type TxtData = any;
}