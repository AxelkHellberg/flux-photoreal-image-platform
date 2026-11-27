import assert from "node:assert/strict";
import { afterEach, mock, test } from "node:test";

import { apiFetch } from "../src/index.ts";

afterEach(() => mock.restoreAll());

for (const [name, headers] of [
  ["Headers instance", new Headers({ Authorization: "Bearer offline-test" })],
  ["header tuples", [["Authorization", "Bearer offline-test"]]],
  ["header record", { Authorization: "Bearer offline-test" }],
]) {
  test(`preserves caller headers from a ${name}`, async () => {
    mock.method(globalThis, "fetch", async (url, init) => {
      assert.equal(url, "https://example.invalid/v1/images");
      const actual = new Headers(init.headers);
      assert.equal(actual.get("authorization"), "Bearer offline-test");
      assert.equal(actual.get("content-type"), "application/json");
      assert.deepEqual([...actual.keys()].sort(), ["authorization", "content-type"]);
      return Response.json({ id: "offline-job" });
    });

    assert.deepEqual(await apiFetch("https://example.invalid", "/v1/images", { headers }), {
      id: "offline-job",
    });
  });
}

for (const [name, headers] of [
  ["Headers instance", new Headers({ "content-type": "text/plain" })],
  ["header tuples", [["content-type", "text/plain"]]],
  ["header record", { "content-type": "text/plain" }],
]) {
  test(`honors a case-insensitive content type override from a ${name}`, async () => {
    mock.method(globalThis, "fetch", async (_url, init) => {
      assert.equal(new Headers(init.headers).get("content-type"), "text/plain");
      return Response.json({});
    });
    await apiFetch("https://example.invalid", "/v1/images", { headers });
    assert.equal(new Headers(headers).get("content-type"), "text/plain");
  });
}

test("keeps request options and defaults without mutating caller Headers", async () => {
  const headers = new Headers({ "X-Request-Id": "offline-test" });
  const controller = new AbortController();
  mock.method(globalThis, "fetch", async (_url, init) => {
    assert.equal(init.method, "POST");
    assert.equal(init.body, "{}");
    assert.equal(init.signal, controller.signal);
    assert.equal(init.cache, "no-store");
    assert.equal(new Headers(init.headers).get("content-type"), "application/json");
    return Response.json({});
  });
  await apiFetch("https://example.invalid", "/v1/images", {
    headers, method: "POST", body: "{}", signal: controller.signal,
  });
  assert.equal(headers.has("content-type"), false);
  assert.equal(headers.get("x-request-id"), "offline-test");
});

test("defaults to JSON when no headers are supplied", async () => {
  mock.method(globalThis, "fetch", async (_url, init) => {
    assert.equal(new Headers(init.headers).get("content-type"), "application/json");
    return Response.json({});
  });
  await apiFetch("https://example.invalid", "/v1/images");
});

test("preserves HTTP failure details", async () => {
  mock.method(globalThis, "fetch", async () => new Response("offline failure", { status: 422 }));
  await assert.rejects(apiFetch("https://example.invalid", "/v1/images"), /offline failure/);
});
