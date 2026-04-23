import { expect, test } from "@playwright/test";

// AC11: trace detail page renders waterfall and events.
test("trace detail renders waterfall", async ({ page }) => {
  await page.route("**/api/trace/abc", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        trace_id: "abc",
        event_count: 2,
        started_ms: 1000,
        ended_ms: 1500,
        total_ms: 500,
        has_error: false,
        events: [
          {
            id: 1, ts_ms: 1000, trace_id: "abc", event: "pipeline_stage",
            duration_ms: 200, status: "ok", slow: 0, stage: "classify",
            tool: null, interface: null, payload_json: "{}",
          },
          {
            id: 2, ts_ms: 1200, trace_id: "abc", event: "tool_call",
            duration_ms: 300, status: "ok", slow: 0, tool: "search_code",
            stage: null, interface: "mcp", payload_json: "{}",
          },
        ],
      }),
    }),
  );
  await page.goto("/trace/abc");
  await expect(page.getByTestId("waterfall")).toBeVisible();
  await expect(page.getByText("classify")).toBeVisible();
  await expect(page.getByText("search_code")).toBeVisible();
  await expect(page.getByText("2 events")).toBeVisible();
});
