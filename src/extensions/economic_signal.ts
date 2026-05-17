// ============================================================
// Maestro Protocol — maestro.economic_signal Extension
// ============================================================
//
// Spec: protocol/extensions/maestro.economic_signal.md
// Status: APPROVED — Hermes/Mnemosyne audited
//
// CRITICAL: This extension transports INTENT ONLY.
// Maestro does not validate, execute, or fulfil value claims.
// The recipient MUST independently verify any claim before acting.
// ============================================================

export const ECONOMIC_SIGNAL_KEY = 'maestro.economic_signal';

export const ECONOMIC_SIGNAL_DISCLAIMER =
  'Maestro is an identity transport protocol. Economic signals are unverified ' +
  'claims of intent. Maestro does not validate or execute them. The recipient ' +
  'MUST independently verify any claim before acting.';

// ----------------------------------------------------------
// Schema
// ----------------------------------------------------------

export interface EconomicSignal {
  /** Symbol or contract address of intended token (non-empty, max 64 chars) */
  token: string;
  /** Decimal amount as string — avoids float precision loss (regex: ^\d+(\.\d+)?$) */
  amount: string;
  /** Human-readable description of the intent (non-empty, max 256 chars) */
  intent: string;
  /** Optional: identifies the target network/ledger context (max 64 chars) */
  chain_id?: string;
}

// ----------------------------------------------------------
// Validation
// ----------------------------------------------------------

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

const AMOUNT_REGEX = /^\d+(\.\d+)?$/;

export function validateEconomicSignal(data: unknown): ValidationResult {
  const errors: string[] = [];

  if (typeof data !== 'object' || data === null) {
    return { valid: false, errors: ['economic_signal must be an object'] };
  }

  const d = data as Record<string, unknown>;

  // token
  if (typeof d['token'] !== 'string' || d['token'].length === 0) {
    errors.push('token: must be a non-empty string');
  } else if (d['token'].length > 64) {
    errors.push('token: must be max 64 chars');
  }

  // amount
  if (typeof d['amount'] !== 'string' || d['amount'].length === 0) {
    errors.push('amount: must be a non-empty string');
  } else if (!AMOUNT_REGEX.test(d['amount'])) {
    errors.push('amount: must be a valid decimal string (e.g. "50.00" or "100")');
  }

  // intent
  if (typeof d['intent'] !== 'string' || d['intent'].length === 0) {
    errors.push('intent: must be a non-empty string');
  } else if (d['intent'].length > 256) {
    errors.push('intent: must be max 256 chars');
  }

  // chain_id (optional)
  if (d['chain_id'] !== undefined) {
    if (typeof d['chain_id'] !== 'string') {
      errors.push('chain_id: must be a string if provided');
    } else if (d['chain_id'].length > 64) {
      errors.push('chain_id: must be max 64 chars');
    }
  }

  return { valid: errors.length === 0, errors };
}

// ----------------------------------------------------------
// Read helper
// ----------------------------------------------------------

/**
 * Extract and validate the economic_signal extension from a message's
 * extensions map. Returns null if not present or invalid.
 *
 * Always logs the mandatory disclaimer when a signal is found.
 */
export function extractEconomicSignal(
  extensions: Record<string, unknown> | undefined,
): EconomicSignal | null {
  if (!extensions) return null;

  const raw = extensions[ECONOMIC_SIGNAL_KEY];
  if (raw === undefined) return null;

  const result = validateEconomicSignal(raw);
  if (!result.valid) {
    console.warn(
      `[economic_signal] Invalid signal received — skipping. Errors: ${result.errors.join('; ')}`,
    );
    return null;
  }

  // Mandatory disclaimer — MUST be surfaced on every signal receipt (spec §5)
  console.log(`[economic_signal] ⚠️  ${ECONOMIC_SIGNAL_DISCLAIMER}`);

  return raw as EconomicSignal;
}

// ----------------------------------------------------------
// Build helper
// ----------------------------------------------------------

/**
 * Build a validated extensions map containing an economic_signal.
 * Throws if the signal fails validation.
 */
export function buildEconomicSignalExtension(
  signal: EconomicSignal,
): Record<string, unknown> {
  const result = validateEconomicSignal(signal);
  if (!result.valid) {
    throw new Error(
      `Invalid economic_signal: ${result.errors.join('; ')}`,
    );
  }
  return { [ECONOMIC_SIGNAL_KEY]: signal };
}

// ----------------------------------------------------------
// Display
// ----------------------------------------------------------

/**
 * Render an economic_signal as a human-readable string with disclaimer.
 * Use this anywhere a signal is surfaced to a user or operator.
 */
export function renderEconomicSignal(signal: EconomicSignal): string {
  const chain = signal.chain_id ? ` on ${signal.chain_id}` : '';
  return [
    '┌─────────────────────────────────────────────┐',
    '│         ECONOMIC INTENT SIGNAL               │',
    '├─────────────────────────────────────────────┤',
    `│ Token:  ${signal.token.padEnd(37)}│`,
    `│ Amount: ${signal.amount.padEnd(37)}│`,
    `│ Chain:  ${(signal.chain_id ?? 'unspecified').padEnd(37)}│`,
    `│ Intent: ${signal.intent.slice(0, 37).padEnd(37)}│`,
    signal.intent.length > 37
      ? `│         ${signal.intent.slice(37, 74).padEnd(37)}│`
      : null,
    '├─────────────────────────────────────────────┤',
    '│ ⚠️  THIS IS AN UNVERIFIED CLAIM OF INTENT   │',
    '│    No execution or fulfillment has occurred │',
    '└─────────────────────────────────────────────┘',
    '',
    ECONOMIC_SIGNAL_DISCLAIMER,
  ]
    .filter(Boolean)
    .join('\n');
}
