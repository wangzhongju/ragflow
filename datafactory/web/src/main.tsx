import { api } from "./api/client";
import { Providers } from "./app/providers";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import {
  RouterProvider,
  createBrowserRouter,
  redirect,
} from "react-router-dom";
import {
  Datasets,
  Login,
  Overview,
  ProjectLayout,
  Projects,
  Releases,
  ReviewDesk,
  Samples,
  Shell,
  Snapshots,
} from "./screens";
import "./styles/tokens.css";

async function requireAuth() {
  if (!localStorage.getItem("Authorization")) return redirect("/login");
  await api.me();
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
        { index: true, loader: () => redirect("/projects") },
        { path: "projects", element: <Projects /> },
        {
          path: "projects/:projectId",
          element: <ProjectLayout />,
          children: [
            { index: true, element: <Overview /> },
            { path: "snapshots", element: <Snapshots /> },
            { path: "runs", lazy: () => import("./features/runs/routes") },
            { path: "datasets", element: <Datasets /> },
            { path: "datasets/:datasetId", element: <Samples /> },
            { path: "review", element: <ReviewDesk /> },
            { path: "releases", element: <Releases /> },
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
