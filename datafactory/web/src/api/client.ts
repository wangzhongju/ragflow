import createClient from "openapi-fetch";
import { v4 as uuid } from "uuid";
import type { components, paths } from "./schema";

const client = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: "same-origin",
});

const MePath = "/api/factory/v1/me";
const SessionPath = "/api/factory/v1/session";

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

client.use({
  onRequest({ request }) {
    if (request.method === "POST")
      request.headers.set("Idempotency-Key", uuid());
    return request;
  },
  onResponse({ response, schemaPath }) {
    if (
      response.status === 401 &&
      schemaPath !== MePath &&
      schemaPath !== SessionPath
    ) {
      window.location.assign("/factory/login");
    }
  },
});

async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await request;
  if (!response.ok) {
    const body = error as { code?: string; message?: string } | undefined;
    throw new ApiError(
      body?.code ?? "error",
      body?.message ?? response.statusText,
      response.status,
    );
  }
  return data as T;
}

const projectParams = (project_id: string) => ({ path: { project_id } });
export const api = {
  adjustBudget: (
    project_id: string,
    run_id: string,
    body: Schema["BudgetIn"],
  ) =>
    unwrap(
      client.PUT("/api/factory/v1/projects/{project_id}/runs/{run_id}/budget", {
        params: { path: { project_id, run_id } },
        body,
      }),
    ),
  reconcile: (
    project_id: string,
    run_id: string,
    invocation_id: string,
    body: Schema["ReconcileIn"],
  ) =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/runs/{run_id}/invocations/{invocation_id}:reconcile",
        { params: { path: { project_id, run_id, invocation_id } }, body },
      ),
    ),
  snapshot: (project_id: string, snapshot_id: string) =>
    unwrap(
      client.GET(
        "/api/factory/v1/projects/{project_id}/snapshots/{snapshot_id}",
        { params: { path: { project_id, snapshot_id } } },
      ),
    ),
  segments: (project_id: string, snapshot_id: string, after?: string) =>
    unwrap(
      client.GET(
        "/api/factory/v1/projects/{project_id}/snapshots/{snapshot_id}/segments",
        {
          params: {
            path: { project_id, snapshot_id },
            query: { limit: 100, after },
          },
        },
      ),
    ),
  login: (body: Schema["LoginIn"]) =>
    unwrap(client.POST(SessionPath, { body })),
  me: () =>
    unwrap(
      client.GET(MePath, {
        headers: {
          Authorization: localStorage.getItem("Authorization") ?? undefined,
        },
      }),
    ),
  projects: () => unwrap(client.GET("/api/factory/v1/projects")),
  createProject: (name: string) =>
    unwrap(
      client.POST("/api/factory/v1/projects", {
        body: { name, description: "" },
      }),
    ),
  overview: (project_id: string) =>
    unwrap(
      client.GET("/api/factory/v1/projects/{project_id}/overview", {
        params: projectParams(project_id),
      }),
    ),
  snapshots: (project_id: string) =>
    unwrap(
      client.GET("/api/factory/v1/projects/{project_id}/snapshots", {
        params: projectParams(project_id),
      }),
    ),
  createSnapshot: (project_id: string, body: Schema["SnapshotIn"]) =>
    unwrap(
      client.POST("/api/factory/v1/projects/{project_id}/snapshots", {
        params: projectParams(project_id),
        body,
      }),
    ),
  recipes: (project_id: string) =>
    unwrap(
      client.GET("/api/factory/v1/projects/{project_id}/recipes", {
        params: projectParams(project_id),
      }),
    ),
  createRecipe: (project_id: string, body: Schema["RecipeIn"]) =>
    unwrap(
      client.POST("/api/factory/v1/projects/{project_id}/recipes", {
        params: projectParams(project_id),
        body,
      }),
    ),
  ragflowDatasets: () => unwrap(client.GET("/api/factory/v1/ragflow/datasets")),
  runs: (project_id: string) =>
    unwrap(
      client.GET("/api/factory/v1/projects/{project_id}/runs", {
        params: projectParams(project_id),
      }),
    ),
  startRun: (project_id: string, body: Schema["RunIn"]) =>
    unwrap(
      client.POST("/api/factory/v1/projects/{project_id}/runs", {
        params: projectParams(project_id),
        body,
      }),
    ),
  cancelRun: (project_id: string, run_id: string) =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/runs/{run_id}:cancel",
        { params: { path: { project_id, run_id } } },
      ),
    ),
  pauseRun: (project_id: string, run_id: string) =>
    unwrap(
      client.POST("/api/factory/v1/projects/{project_id}/runs/{run_id}:pause", {
        params: { path: { project_id, run_id } },
      }),
    ),
  resumeRun: (project_id: string, run_id: string) =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/runs/{run_id}:resume",
        { params: { path: { project_id, run_id } } },
      ),
    ),
  runMetrics: (project_id: string, run_id: string, after?: string) =>
    unwrap(
      client.GET(
        "/api/factory/v1/projects/{project_id}/runs/{run_id}/metrics",
        { params: { path: { project_id, run_id }, query: { after } } },
      ),
    ),
  previewRecipe: (
    project_id: string,
    recipe_id: string,
    body: Schema["PreviewIn"],
  ) =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/recipes/{recipe_id}:preview",
        { params: { path: { project_id, recipe_id } }, body },
      ),
    ),
  datasets: (project_id: string) =>
    unwrap(
      client.GET("/api/factory/v1/projects/{project_id}/datasets", {
        params: projectParams(project_id),
      }),
    ),
  samples: (project_id: string, dataset_id: string) =>
    unwrap(
      client.GET(
        "/api/factory/v1/projects/{project_id}/datasets/{dataset_id}/samples",
        { params: { path: { project_id, dataset_id } } },
      ),
    ),
  reviewQueue: (project_id: string) =>
    unwrap(
      client.GET("/api/factory/v1/projects/{project_id}/review-queue", {
        params: projectParams(project_id),
      }),
    ),
  review: (project_id: string, sample_id: string, body: Schema["ReviewIn"]) =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/samples/{sample_id}/reviews",
        { params: { path: { project_id, sample_id } }, body },
      ),
    ),
  releases: (project_id: string) =>
    unwrap(
      client.GET("/api/factory/v1/projects/{project_id}/releases", {
        params: projectParams(project_id),
      }),
    ),
  release: (project_id: string, dataset_id: string, warning_reason = "") =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/datasets/{dataset_id}/releases",
        {
          params: { path: { project_id, dataset_id } },
          body: { warning_reason },
        },
      ),
    ),
  export: (project_id: string, release_id: string, adapter: string) =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/releases/{release_id}:export",
        { params: { path: { project_id, release_id }, query: { adapter } } },
      ),
    ),
  downloadPackage: (project_id: string, release_id: string, adapter: string) =>
    unwrap(
      client.GET(
        "/api/factory/v1/projects/{project_id}/releases/{release_id}/package",
        {
          params: { path: { project_id, release_id }, query: { adapter } },
          parseAs: "blob",
        },
      ),
    ),
};

type Schema = components["schemas"];
export type ContentPart = Schema["ContentPart"];
export function assetUrl(asset: string) {
  return `/api/factory/v1/assets/${encodeURIComponent(asset)}`;
}
export type Me = Schema["Me"];
export type Project = Schema["ProjectOut"];
export type Snapshot = Schema["SnapshotOut"];
export type Recipe = Schema["RecipeSummary"];
export type Run = Schema["RunRecord"];
export type RunMetrics = Schema["RunMetrics"];
export type Dataset = Schema["DatasetRecord"];
export type Sample = Schema["SampleRecord"];
export type Release = Schema["ReleaseRecord"];
export type OverviewCounts = Schema["OverviewRecord"];
export type RagflowDataset = Schema["Dataset"];

export function watchRun(
  projectId: string,
  runId: string,
  onRun: (run: Run) => void,
  onConnection: (connected: boolean) => void,
): () => void {
  const source = new EventSource(
    `/api/factory/v1/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/events`,
  );
  source.onopen = () => onConnection(true);
  source.onerror = () => onConnection(false);
  source.addEventListener("run", (event: MessageEvent<string>) => {
    try {
      const run: Run = JSON.parse(event.data);
      onRun(run);
      if (!["queued", "running"].includes(run.status)) source.close();
    } catch {
      onConnection(false);
      source.close();
    }
  });
  source.addEventListener("access-revoked", () => {
    onConnection(false);
    source.close();
  });
  return () => source.close();
}
