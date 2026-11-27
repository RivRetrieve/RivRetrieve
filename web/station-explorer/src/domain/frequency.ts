const ELAPSED_RE = /^PT(?:([0-9]+)H)?(?:([0-9]+)M)?(?:([0-9]+)S)?$/;
const CALENDAR_DAYS_RE = /^P(?:([0-9]+)W)?(?:([0-9]+)D)?$/;
const CALENDAR_MONTHS_RE = /^P(?:([0-9]+)Y)?(?:([0-9]+)M)?$/;

function parseOptionalBigInt(raw: string | undefined): bigint {
  return raw === undefined ? 0n : BigInt(raw);
}

/** Canonicalize an ISO 8601 duration string within one supported family, or return null. */
export function canonicalizeFrequency(raw: string): string | null {
  const elapsed = ELAPSED_RE.exec(raw);
  if (
    elapsed &&
    (elapsed[1] !== undefined ||
      elapsed[2] !== undefined ||
      elapsed[3] !== undefined)
  ) {
    const totalSeconds =
      parseOptionalBigInt(elapsed[1]) * 3600n +
      parseOptionalBigInt(elapsed[2]) * 60n +
      parseOptionalBigInt(elapsed[3]);
    if (totalSeconds <= 0n) return null;
    if (totalSeconds % 3600n === 0n) return `PT${totalSeconds / 3600n}H`;
    if (totalSeconds % 60n === 0n) return `PT${totalSeconds / 60n}M`;
    return `PT${totalSeconds}S`;
  }
  const days = CALENDAR_DAYS_RE.exec(raw);
  if (days && (days[1] !== undefined || days[2] !== undefined)) {
    const totalDays =
      parseOptionalBigInt(days[1]) * 7n + parseOptionalBigInt(days[2]);
    if (totalDays <= 0n) return null;
    if (totalDays % 7n === 0n) return `P${totalDays / 7n}W`;
    return `P${totalDays}D`;
  }
  const months = CALENDAR_MONTHS_RE.exec(raw);
  if (months && (months[1] !== undefined || months[2] !== undefined)) {
    const totalMonths =
      parseOptionalBigInt(months[1]) * 12n + parseOptionalBigInt(months[2]);
    if (totalMonths <= 0n) return null;
    if (totalMonths % 12n === 0n) return `P${totalMonths / 12n}Y`;
    return `P${totalMonths}M`;
  }
  return null;
}

/** Return a validation message for an invalid non-empty frequency filter, or null. */
export function frequencyError(raw: string | undefined): string | null {
  if (raw === undefined || raw === "") return null;
  if (canonicalizeFrequency(raw) !== null) return null;
  return 'Enter a positive ISO 8601 duration in one family, such as "PT15M", "PT1H", "P1D", "P1W", "P1M", or "P1Y".';
}
