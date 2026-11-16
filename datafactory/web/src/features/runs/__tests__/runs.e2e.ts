import { test, expect } from "@playwright/test";
import type {
  Run,
  RunMetrics,
  Project,
  Recipe,
  Snapshot,
} from "../../../api/client";

const ProjectFixture: Project = {
  id: "p",
  name: "运行引擎验收",
  description: "",
  owner_id: "u",
  role: "owner",
};
const RecipeFixture: Recipe = {
  id: "r",
  project_id: "p",
  name: "检索样本制作",
  task: "retrieval",
  status: "draft",
  version: 2,
};
const SnapshotFixture: Snapshot = {
  id: "s",
  project_id: "p",
  name: "开发语料快照",
  status: "ready",
  sources: [],
  vector_profile: [],
  stats: {},
  created_by: "u",
};
const RunFixture: Run = {
  id: "run_checkpoint_demo",
  project_id: "p",
  recipe_id: "r",
  recipe_version_id: "rcv_frozen_version_2",
  snapshot_id: "s",
  status: "paused",
  mode: "run",
  sample_count: 0,
  limit: 128,
  error: "",
  seed: 17,
  batch_size: 64,
  attempt_generation: 2,
  completed_units: 3,
  total_units: 8,
  max_invocations: 1000,
  max_tokens: 1000000,
  used_tokens: 8420,
  reserved_tokens: 2048,
  invocation_count: 65,
  preview: [],
};
const Metrics: RunMetrics = {
  run: RunFixture,
  checkpoints: [
    {
      stage: 0,
      column: "qa",
      batches: 2,
      rows: 128,
      elapsed_ms: 8400,
      attempt_generation: 1,
    },
    {
      stage: 1,
      column: "teacher_scores",
      batches: 1,
      rows: 64,
      elapsed_ms: 3200,
      attempt_generation: 1,
    },
  ],
  invocations: [
    {
      id: "inv_1",
      column: "qa",
      row_key: "seg_001",
      model_id: "开发生成模型",
      model_fingerprint: "model-fingerprint",
      status: "succeeded",
      token_upper_bound: 2048,
      usage: { total_tokens: 120 },
      latency_ms: 200,
      error: "",
    },
  ],
};

test("run workbench renders in both themes and a narrow viewport", async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() =>
    localStorage.setItem("Authorization", "local-test-token"),
  );
  await page.route("**/api/factory/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path.endsWith("/me"))
      body = { user_id: "u", tenant_ids: [], nickname: "开发验收", lang: "zh" };
    else if (path.endsWith("/projects")) body = [ProjectFixture];
    else if (path.endsWith("/projects/p")) body = ProjectFixture;
    else if (path.endsWith("/overview"))
      body = {
        datasets: 0,
        samples: 0,
        pending_reviews: 0,
        running: 0,
        releases: 0,
      };
    else if (path.endsWith("/recipes")) body = [RecipeFixture];
    else if (path.endsWith("/snapshots")) body = [SnapshotFixture];
    else if (path.endsWith("/runs")) body = [RunFixture];
    else if (path.endsWith("/metrics")) body = Metrics;
    else if (path.endsWith("/events")) {
      await route.fulfill({
        contentType: "text/event-stream",
        body: `event: run\ndata: ${JSON.stringify(RunFixture)}\n\n`,
      });
      return;
    } else throw new Error(`Unexpected request: ${path}`);
    await route.fulfill({ json: body });
  });
  await page.goto("/factory/projects/p/runs?run=run_checkpoint_demo");
  await expect(page.getByText("rcv_frozen_version_2")).toBeVisible();
  await expect(page.getByRole("button", { name: "继续" })).toBeVisible();
  await expect(page.getByRole("progressbar")).toHaveAttribute("value", "3");
  await page.screenshot({
    path: testInfo.outputPath("runs-light.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "切换亮 / 暗主题" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({
    path: testInfo.outputPath("runs-dark.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 900, height: 1000 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("runs-narrow.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
