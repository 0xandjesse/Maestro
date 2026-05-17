// ============================================================
// Maestro Protocol — maestro.economic_signal Extension Tests
// ============================================================

import {
  validateEconomicSignal,
  extractEconomicSignal,
  buildEconomicSignalExtension,
  renderEconomicSignal,
  ECONOMIC_SIGNAL_KEY,
  ECONOMIC_SIGNAL_DISCLAIMER,
} from '../extensions/economic_signal.js';
import { jest } from '@jest/globals';

// ----------------------------------------------------------
// validateEconomicSignal
// ----------------------------------------------------------

describe('validateEconomicSignal', () => {
  it('valid signal with all fields passes', () => {
    const result = validateEconomicSignal({
      token: 'ETH',
      amount: '50.5',
      intent: 'Payment for services rendered',
      chain_id: 'ethereum',
    });
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('valid signal without chain_id passes', () => {
    const result = validateEconomicSignal({
      token: 'BTC',
      amount: '100',
      intent: 'Donation',
    });
    expect(result.valid).toBe(true);
    expect(result.errors).toHaveLength(0);
  });

  it('empty token fails', () => {
    const result = validateEconomicSignal({
      token: '',
      amount: '10',
      intent: 'Payment',
    });
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('token: must be a non-empty string');
  });

  it('amount "50.5.5" fails regex', () => {
    const result = validateEconomicSignal({
      token: 'ETH',
      amount: '50.5.5',
      intent: 'Payment',
    });
    expect(result.valid).toBe(false);
    expect(result.errors).toContain(
      'amount: must be a valid decimal string (e.g. "50.00" or "100")',
    );
  });

  it('intent over 256 chars fails', () => {
    const result = validateEconomicSignal({
      token: 'ETH',
      amount: '1',
      intent: 'a'.repeat(257),
    });
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('intent: must be max 256 chars');
  });

  // (1) null input
  it('null input fails with object error', () => {
    const result = validateEconomicSignal(null);
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('object'))).toBe(true);
  });

  // (2) non-object string input
  it('string input "hello" fails with object error', () => {
    const result = validateEconomicSignal('hello');
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('object'))).toBe(true);
  });

  // (3) token exactly 64 chars passes
  it('token exactly 64 chars passes', () => {
    const result = validateEconomicSignal({
      token: 'a'.repeat(64),
      amount: '10',
      intent: 'Payment',
    });
    expect(result.valid).toBe(true);
  });

  // (4) token 65 chars fails
  it('token 65 chars fails', () => {
    const result = validateEconomicSignal({
      token: 'a'.repeat(65),
      amount: '10',
      intent: 'Payment',
    });
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('token: must be max 64 chars');
  });

  // (5) chain_id exactly 64 chars passes
  it('chain_id exactly 64 chars passes', () => {
    const result = validateEconomicSignal({
      token: 'ETH',
      amount: '10',
      intent: 'Payment',
      chain_id: 'a'.repeat(64),
    });
    expect(result.valid).toBe(true);
  });

  // (6) chain_id 65 chars fails
  it('chain_id 65 chars fails', () => {
    const result = validateEconomicSignal({
      token: 'ETH',
      amount: '10',
      intent: 'Payment',
      chain_id: 'a'.repeat(65),
    });
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('chain_id: must be max 64 chars');
  });

  // (7) chain_id as number fails with string error
  it('chain_id as number 42 fails with string error', () => {
    const result = validateEconomicSignal({
      token: 'ETH',
      amount: '10',
      intent: 'Payment',
      chain_id: 42,
    });
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('string'))).toBe(true);
  });

  // (8) empty intent fails
  it('empty intent fails', () => {
    const result = validateEconomicSignal({
      token: 'ETH',
      amount: '10',
      intent: '',
    });
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('intent: must be a non-empty string');
  });

  // (9) amount as number 100 fails
  it('amount as number 100 fails', () => {
    const result = validateEconomicSignal({
      token: 'ETH',
      amount: 100,
      intent: 'Payment',
    });
    expect(result.valid).toBe(false);
    expect(result.errors.some((e) => e.includes('amount'))).toBe(true);
  });

  // (10) multiple simultaneous errors: empty token + bad amount + intent >256 chars
  it('multiple simultaneous errors accumulate (>=3 errors)', () => {
    const result = validateEconomicSignal({
      token: '',
      amount: '50.5.5',
      intent: 'a'.repeat(257),
    });
    expect(result.valid).toBe(false);
    expect(result.errors.length).toBeGreaterThanOrEqual(3);
  });
});

// ----------------------------------------------------------
// extractEconomicSignal
// ----------------------------------------------------------

describe('extractEconomicSignal', () => {
  it('returns null when extensions undefined', () => {
    expect(extractEconomicSignal(undefined)).toBeNull();
  });

  it('returns null when key absent', () => {
    expect(extractEconomicSignal({ other_key: 'value' })).toBeNull();
  });

  it('returns typed signal for valid payload', () => {
    const extensions = {
      [ECONOMIC_SIGNAL_KEY]: {
        token: 'USDC',
        amount: '1000.00',
        intent: 'Invoice #1234',
        chain_id: 'polygon',
      },
    };
    const signal = extractEconomicSignal(extensions);
    expect(signal).not.toBeNull();
    expect(signal!.token).toBe('USDC');
    expect(signal!.amount).toBe('1000.00');
    expect(signal!.intent).toBe('Invoice #1234');
    expect(signal!.chain_id).toBe('polygon');
  });

  // (11) key present but invalid payload — returns null and warns
  it('key present but invalid payload (token:"") returns null and warns', () => {
    const warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
    const extensions = {
      [ECONOMIC_SIGNAL_KEY]: {
        token: '',
        amount: '10',
        intent: 'Payment',
      },
    };
    const signal = extractEconomicSignal(extensions);
    expect(signal).toBeNull();
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});

// ----------------------------------------------------------
// buildEconomicSignalExtension
// ----------------------------------------------------------

describe('buildEconomicSignalExtension', () => {
  it('throws on invalid signal', () => {
    expect(() =>
      buildEconomicSignalExtension({
        token: '',
        amount: 'bad',
        intent: '',
      }),
    ).toThrow('Invalid economic_signal');
  });

  it('returns correct extensions map on valid', () => {
    const signal = {
      token: 'DAI',
      amount: '500',
      intent: 'Grant disbursement',
      chain_id: 'gnosis',
    };
    const ext = buildEconomicSignalExtension(signal);
    expect(ext).toEqual({ [ECONOMIC_SIGNAL_KEY]: signal });
  });

  // (12) valid signal WITHOUT chain_id — no throw, map contains key
  it('valid signal without chain_id does not throw and contains key', () => {
    const signal = {
      token: 'ETH',
      amount: '1',
      intent: 'Payment',
    };
    let ext: Record<string, unknown> | undefined;
    expect(() => {
      ext = buildEconomicSignalExtension(signal);
    }).not.toThrow();
    expect(ext).toBeDefined();
    expect(Object.keys(ext!)).toContain(ECONOMIC_SIGNAL_KEY);
  });
});

// ----------------------------------------------------------
// renderEconomicSignal
// ----------------------------------------------------------

describe('renderEconomicSignal', () => {
  it('output contains ECONOMIC_SIGNAL_DISCLAIMER', () => {
    const output = renderEconomicSignal({
      token: 'ETH',
      amount: '10',
      intent: 'Test',
    });
    expect(output).toContain(ECONOMIC_SIGNAL_DISCLAIMER);
  });

  // (13) no chain_id — output contains 'unspecified'
  it('no chain_id renders "unspecified"', () => {
    const output = renderEconomicSignal({
      token: 'ETH',
      amount: '10',
      intent: 'Test',
    });
    expect(output).toContain('unspecified');
  });

  // (14) box structure — output contains token and amount values
  it('box structure contains token and amount values', () => {
    const output = renderEconomicSignal({
      token: 'USDC',
      amount: '999.99',
      intent: 'Invoice',
      chain_id: 'ethereum',
    });
    expect(output).toContain('USDC');
    expect(output).toContain('999.99');
  });

  // (15) intent over 74 chars — second line present with trailing content
  it('intent over 74 chars wraps onto second line', () => {
    const longIntent = 'a'.repeat(75);
    const output = renderEconomicSignal({
      token: 'ETH',
      amount: '1',
      intent: longIntent,
      chain_id: 'mainnet',
    });
    // The second intent line should contain chars 37-74 of the intent
    expect(output).toContain(longIntent.slice(37, 74));
  });
});
