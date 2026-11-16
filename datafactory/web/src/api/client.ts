import createClient from "openapi-fetch";
import { v4 as uuid } from "uuid";
import type { components, paths } from "./schema";

const client = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: "same-origin",
});

export class ApiError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

function token(): string {
  return localStorage.getItem("Authorization") ?? "";
}

client.use({
  onRequest({ request }) {
    request.headers.set("Authorization", token());
    if (request.method === "POST")
      request.headers.set("Idempotency-Key", uuid());
    return request;
  },
  onResponse({ response }) {
    if (response.status === 401) {
      localStorage.removeItem("Authorization");
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
  me: () => unwrap(client.GET("/api/factory/v1/me")),
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
  release: (project_id: string, dataset_id: string) =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/datasets/{dataset_id}/releases",
        { params: { path: { project_id, dataset_id } } },
      ),
    ),
  export: (project_id: string, release_id: string, adapter: string) =>
    unwrap(
      client.POST(
        "/api/factory/v1/projects/{project_id}/releases/{release_id}:export",
        { params: { path: { project_id, release_id }, query: { adapter } } },
      ),
    ),
};

type Schema = components["schemas"];
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

export async function login(email: string, password: string): Promise<void> {
  const response = await fetch("/v1/user/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "same-origin",
  });
  const authorization = response.headers.get("Authorization");
  if (!response.ok || !authorization)
    throw new ApiError(
      "login_failed",
      "登录失败，请检查邮箱和密码。",
      response.status,
    );
  localStorage.setItem("Authorization", authorization);
  await api.me();
}
