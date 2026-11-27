import type { RequestDates } from "./types";

/** Check whether a date string is a real YYYY-MM-DD calendar date. */
export function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.slice(0, 4) === "0000")
    return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

/** Validate retrieval start and optional end dates, returning per-field error messages. */
export function dateErrors(
  dates: RequestDates,
): Partial<Record<keyof RequestDates, string>> {
  const errors: Partial<Record<keyof RequestDates, string>> = {};
  if (!validDate(dates.start))
    errors.start = "Enter a valid start date (YYYY-MM-DD).";
  if (dates.end && !validDate(dates.end))
    errors.end = "Enter a valid end date (YYYY-MM-DD).";
  if (validDate(dates.start) && validDate(dates.end) && dates.start > dates.end)
    errors.end = "Start date must not be after end date.";
  return errors;
}
