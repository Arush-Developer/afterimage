import { humanize, relativeTime, shortHash } from "./format";

describe("format helpers", () => {
  it("humanizes snake_case", () => {
    expect(humanize("exposure_confirmed")).toBe("Exposure confirmed");
    expect(humanize(null)).toBe("—");
  });
  it("shortens hashes", () => {
    expect(shortHash("a".repeat(64), 8)).toBe("aaaaaaaa…");
    expect(shortHash("abc")).toBe("abc");
  });
  it("formats relative time", () => {
    const now = Date.parse("2026-01-01T12:00:00Z");
    expect(relativeTime("2026-01-01T11:58:00Z", now)).toBe("2m ago");
    expect(relativeTime("2026-01-01T12:00:00Z", now)).toBe("just now");
  });
});
