import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { Server } from "../../../lib/test-server";
import { Component } from "../routes";
import type { Run, RunMetrics, Recipe, Snapshot } from "../../../api/client";
import "../../../app/providers";

const RunFixture: Run = {
  id: "run_1",
  project_id: "p",
  recipe_id: "recipe_1",
  snapshot_id: "snap_1",
  status: "paused",
  sample_count: 0,
  limit: 10,
  error: "",
  recipe_version_id: "version_1",
  mode: "run",
  seed: 17,
  batch_size: 64,
  attempt_generation: 2,
  completed_units: 1,
  total_units: 3,
  max_invocations: 100,
  max_tokens: 10000,
  reserved_tokens: 80,
  used_tokens: 20,
  invocation_count: 1,
  preview: [],
};
const MetricsFixture: RunMetrics = {
  run: RunFixture,
  checkpoints: [],
  invocations: [],
  next_invocation_cursor: null,
};
const Recipes: Recipe[] = [1, 2].map((id) => ({
  id: `recipe_${id}`,
  project_id: "p",
  name: `Recipe ${id}`,
  task: "retrieval",
  status: "draft",
  version: 0,
}));
const Snapshots: Snapshot[] = [
  {
    id: "snap_1",
    project_id: "p",
    name: "Snapshot",
    status: "ready",
    sources: [],
    vector_profile: [],
    stats: {},
    created_by: "u",
  },
];
const Prefix = "*/api/factory/v1/projects/p";
const Handlers = [
  http.get(`${Prefix}/runs`, () => HttpResponse.json([RunFixture])),
  http.get(`${Prefix}/recipes`, () => HttpResponse.json(Recipes)),
  http.get(`${Prefix}/snapshots`, () => HttpResponse.json(Snapshots)),
  http.get(`${Prefix}/runs/run_1/metrics`, () =>
    HttpResponse.json(MetricsFixture),
  ),
];
beforeAll(() => {
  Server.use(...Handlers);
  vi.stubGlobal(
    "EventSource",
    class {
      addEventListener() {}
      close() {}
    },
  );
});
afterEach(() => {
  cleanup();
  Server.resetHandlers(...Handlers);
  vi.restoreAllMocks();
});
afterAll(() => {
  Server.close();
  vi.unstubAllGlobals();
});

function mount(path = "/projects/p/runs?run=run_1") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects/:projectId/runs" element={<Component />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Run workbench", () => {
  it("shows partial progress, frozen version and resume control", async () => {
    mount();
    expect(await screen.findByText("version_1")).toBeTruthy();
    expect(screen.getByRole("button", { name: "继续" })).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("value")).toBe("1");
    expect(
      screen.getByText("运行尚未完成，已保存的检查点会在续跑时复用。"),
    ).toBeTruthy();
  });
  it("submits the explicitly selected recipe", async () => {
    let body: unknown;
    Server.use(
      http.post(`${Prefix}/runs`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(RunFixture);
      }),
    );
    mount("/projects/p/runs");
    await screen.findByRole("option", { name: "Recipe 2 · v0" });
    fireEvent.change(screen.getByLabelText("配方"), {
      target: { value: "recipe_2" },
    });
    fireEvent.change(screen.getByLabelText("快照"), {
      target: { value: "snap_1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "正式运行" }));
    await waitFor(() =>
      expect(body).toEqual({
        recipe_id: "recipe_2",
        snapshot_id: "snap_1",
        limit: 10,
      }),
    );
  });
  it("does not cancel when confirmation is declined", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "取消" }));
    expect(confirm).toHaveBeenCalledOnce();
  });
  it("renders a retryable detail failure", async () => {
    Server.use(
      http.get(`${Prefix}/runs/run_1/metrics`, () =>
        HttpResponse.json({ message: "Unavailable" }, { status: 503 }),
      ),
    );
    mount();
    expect(await screen.findByText("Unavailable")).toBeTruthy();
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
  });
  it("renders the empty list without auto selecting a recipe", async () => {
    Server.use(http.get(`${Prefix}/runs`, () => HttpResponse.json([])));
    mount("/projects/p/runs");
    expect(
      await screen.findByText("暂无运行。选择配方和就绪快照，先预览制作结果。"),
    ).toBeTruthy();
    expect((screen.getByLabelText("配方") as HTMLSelectElement).value).toBe("");
  });
});
