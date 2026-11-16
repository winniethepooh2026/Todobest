import assert from "node:assert/strict";
import { test } from "node:test";

import {
  calendarDateInTimeZone,
  normalizeTimeZone,
  toZonedDateTimeInput,
  zonedDateTimeInputToISOString,
} from "./timezone";

test("timezone helpers round-trip a regular local time", () => {
  const iso = zonedDateTimeInputToISOString(
    "2026-08-13T18:00",
    "Asia/Tashkent",
  );

  assert.equal(iso, "2026-08-13T13:00:00.000Z");
  assert.equal(toZonedDateTimeInput(iso, "Asia/Tashkent"), "2026-08-13T18:00");
});

test("timezone helpers reject a spring-forward gap", () => {
  assert.throws(
    () => zonedDateTimeInputToISOString("2026-03-08T02:30", "America/New_York"),
    RangeError,
  );
});

test("timezone helpers choose the earlier instant in a fall-back fold", () => {
  assert.equal(
    zonedDateTimeInputToISOString("2026-11-01T01:30", "America/New_York"),
    "2026-11-01T05:30:00.000Z",
  );
});

test("calendar day follows the profile timezone rather than the browser", () => {
  const day = calendarDateInTimeZone(
    new Date("2026-08-13T20:30:00.000Z"),
    "Asia/Tashkent",
  );

  assert.equal(day.getFullYear(), 2026);
  assert.equal(day.getMonth(), 7);
  assert.equal(day.getDate(), 14);
});

test("an invalid stored timezone falls back without crashing", () => {
  const safeTimeZone = normalizeTimeZone("Not/AZone");
  assert.doesNotThrow(() =>
    calendarDateInTimeZone(new Date("2026-08-13T12:00:00.000Z"), safeTimeZone),
  );
  assert.notEqual(safeTimeZone, "Not/AZone");
});
