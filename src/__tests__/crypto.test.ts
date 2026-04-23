import { generateKeyPair, getPublicKey, sign, verify, hashString, hashConcat, originalSignaturePayload, attestationPayload } from '../crypto/index.js';

describe('Crypto primitives', () => {
  describe('Key generation', () => {
    it('generates a valid key pair', () => {
      const { privateKey, publicKey } = generateKeyPair();
      expect(privateKey).toHaveLength(64); // 32 bytes hex
      expect(publicKey).toHaveLength(64);
    });

    it('derives correct public key from private key', () => {
      const { privateKey, publicKey } = generateKeyPair();
      expect(getPublicKey(privateKey)).toBe(publicKey);
    });

    it('generates unique key pairs', () => {
      const kp1 = generateKeyPair();
      const kp2 = generateKeyPair();
      expect(kp1.privateKey).not.toBe(kp2.privateKey);
      expect(kp1.publicKey).not.toBe(kp2.publicKey);
    });
  });

  describe('Sign and verify', () => {
    it('verifies a valid signature', async () => {
      const { privateKey, publicKey } = generateKeyPair();
      const message = 'hello maestro';
      const sig = await sign(message, privateKey);
      expect(await verify(message, sig, publicKey)).toBe(true);
    });

    it('rejects a tampered message', async () => {
      const { privateKey, publicKey } = generateKeyPair();
      const sig = await sign('original', privateKey);
      expect(await verify('tampered', sig, publicKey)).toBe(false);
    });

    it('rejects a wrong public key', async () => {
      const kp1 = generateKeyPair();
      const kp2 = generateKeyPair();
      const sig = await sign('hello', kp1.privateKey);
      expect(await verify('hello', sig, kp2.publicKey)).toBe(false);
    });

    it('rejects a malformed signature', async () => {
      const { publicKey } = generateKeyPair();
      expect(await verify('hello', 'deadbeef'.repeat(8), publicKey)).toBe(false);
    });
  });

  describe('Hashing', () => {
    it('produces consistent hashes', () => {
      expect(hashString('hello')).toBe(hashString('hello'));
    });

    it('produces different hashes for different inputs', () => {
      expect(hashString('hello')).not.toBe(hashString('world'));
    });

    it('hashConcat joins and hashes', () => {
      expect(hashConcat('a', 'b', 'c')).toBe(hashString('abc'));
    });
  });

  describe('Payload helpers', () => {
    it('originalSignaturePayload is deterministic', () => {
      const p1 = originalSignaturePayload('content', 1000, 'Alpha');
      const p2 = originalSignaturePayload('content', 1000, 'Alpha');
      expect(p1).toBe(p2);
    });

    it('attestationPayload is deterministic', () => {
      const p1 = attestationPayload('prevSig', 'contentHash', 1001);
      const p2 = attestationPayload('prevSig', 'contentHash', 1001);
      expect(p1).toBe(p2);
    });

    it('originalSignaturePayload differs with different inputs', () => {
      expect(originalSignaturePayload('a', 1000, 'Alpha'))
        .not.toBe(originalSignaturePayload('b', 1000, 'Alpha'));
    });
  });
});
