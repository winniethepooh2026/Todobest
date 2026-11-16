import assert from "node:assert/strict";
import test from "node:test";

import { safeAppReturnTo } from "./utils.js";

test("safeAppReturnTo accepts only local application routes", () => {
  const fallback = "/app/my-issues";

  assert.equal(
    safeAppReturnTo("/app/tasks/123?tab=activity#latest", fallback),
    "/app/tasks/123?tab=activity#latest",
  );
  assert.equal(safeAppReturnTo("javascript:alert(1)", fallback), fallback);
  assert.equal(safeAppReturnTo("https://evil.example/app", fallback), fallback);
  assert.equal(safeAppReturnTo("//evil.example/app", fallback), fallback);
  assert.equal(safeAppReturnTo("/pricing", fallback), fallback);
});
