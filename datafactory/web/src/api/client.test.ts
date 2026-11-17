import { afterEach, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { Server } from "../lib/test-server";
import { api } from "./client";

afterEach(() => {
  localStorage.clear();
  Server.resetHandlers();
});

it("signs in to DataFactory without replacing the browser's RAGFlow token", async () => {
  localStorage.setItem("Authorization", "existing-ragflow-token");
  Server.use(
    http.post("*/api/factory/v1/session", async ({ request }) => {
      expect(await request.json()).toEqual({
        email: "user@example.org",
        password: "encrypted",
      });
      expect(request.headers.get("Authorization")).toBeNull();
      return HttpResponse.json({
        user_id: "u",
        tenant_ids: [],
        nickname: "",
        lang: "zh",
      });
    }),
  );
  await expect(
    api.login({ email: "user@example.org", password: "encrypted" }),
  ).resolves.toMatchObject({ user_id: "u" });
  expect(localStorage.getItem("Authorization")).toBe("existing-ragflow-token");
});
