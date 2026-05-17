import { Maestro } from '../dist/index.js';

// Use a fresh port so we don't conflict with the running service
const songbird = new Maestro({
  agentId: 'songbird',
  transport: { port: 3850, registryPath: '.maestro/registry.json' },
  openclaw: {
    gatewayUrl: 'http://127.0.0.1:18789',
    hookToken: '06fe84970c2ba322f6e59e007145f015f862be85e72823265fad2b3b8ced1069',
    agentSessions: {
      songbird: 'agent:songbird:main',
      lexicon: 'agent:lexicon:telegram:direct:8244638936'
    }
  }
});

await songbird.start();
await new Promise(r => setTimeout(r, 500));

console.log('Sending message to Lex via transport...');
const result = await songbird.sendDirect(
  'lexicon',
  'Lex — this is Songbird. First live Maestro transport test. The transport is running as a persistent service now. If you got this, please confirm to Jesse in TG that you received a direct Maestro message from Songbird. 🎸'
);
console.log('Result:', JSON.stringify(result));

await songbird.stop();
