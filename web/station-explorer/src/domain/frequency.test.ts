import { describe, expect, it } from "vitest";
import { canonicalizeFrequency, frequencyError } from "./frequency";

describe("canonical ISO 8601 frequency handling", () => {
  it("reduces elapsed, calendar-day, and calendar-month families without cross-family conversion", () => {
    expect(canonicalizeFrequency("PT60M")).toBe("PT1H");
    expect(canonicalizeFrequency("PT900S")).toBe("PT15M");
    expect(canonicalizeFrequency("PT24H")).toBe("PT24H");
    expect(canonicalizeFrequency("P7D")).toBe("P1W");
    expect(canonicalizeFrequency("P14D")).toBe("P2W");
    expect(canonicalizeFrequency("P12M")).toBe("P1Y");
    expect(canonicalizeFrequency("P1M")).toBe("P1M");
  });

  it("rejects non-ISO tokens, mixed families, and zero durations", () => {
    for (const invalid of ["daily", "PT0S", "P0D", "P1DT1H", "P1Y2D", "pt15m", "1D"]) {
      expect(canonicalizeFrequency(invalid)).toBeNull();
      expect(frequencyError(invalid)).toContain("positive ISO 8601 duration");
    }
    expect(frequencyError(undefined)).toBeNull();
    expect(frequencyError("")).toBeNull();
  });
});
