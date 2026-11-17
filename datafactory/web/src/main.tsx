import { api, ApiError } from "./api/client";
import { Login } from "./app/login";
import { Providers } from "./app/providers";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import {
  Navigate,
  RouterProvider,
  createBrowserRouter,
  redirect,
} from "react-router-dom";
import {
  Datasets,
  Overview,
  ProjectLayout,
  Projects,
  ReviewDesk,
  Samples,
  Shell,
  Snapshots,
} from "./screens";
import "./styles/tokens.css";

async function requireAuth() {
  try {
    await api.me();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401)
      return redirect("/login");
    throw error;
  }
  return null;
}

const router = createBrowserRouter(
  [
    { path: "/login", element: <Login /> },
    {
      path: "/",
      element: <Shell />,
      loader: requireAuth,
      children: [
        { index: true, element: <Navigate to="/projects" replace /> },
        { path: "projects", element: <Projects /> },
        {
          path: "projects/:projectId",
          element: <ProjectLayout />,
          children: [
            { index: true, element: <Overview /> },
            { path: "snapshots", element: <Snapshots /> },
            {
              path: "snapshots/:snapshotId",
              lazy: () => import("./features/corpus/routes"),
            },
            { path: "runs", lazy: () => import("./features/runs/routes") },
            { path: "datasets", element: <Datasets /> },
            { path: "datasets/:datasetId", element: <Samples /> },
            { path: "review", element: <ReviewDesk /> },
            {
              path: "releases",
              lazy: () => import("./features/releases/routes"),
            },
          ],
        },
      ],
    },
  ],
  { basename: "/factory" },
);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Providers>
      <RouterProvider router={router} />
    </Providers>
  </StrictMode>,
);
