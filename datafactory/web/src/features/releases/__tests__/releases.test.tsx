import { afterEach, beforeAll, describe, expect, it } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { Server } from "../../../lib/test-server";
import { ReleaseWorkbench } from "../workbench";
import type { Release, Dataset } from "../../../api/client";
import "../../../app/providers";

const Prefix = "*/api/factory/v1/projects/p";
const ReleaseFixture: Release = {
  id: "rel",
  dataset_id: "d2",
  status: "blocked",
  sample_count: 1,
  gates: [
    {
      name: "judge_score",
      level: "blocker",
      passed: false,
      detail: "Missing score",
    },
  ],
  manifest: {},
};
const Datasets: Dataset[] = [1, 2].map((id) => ({
  id: `d${id}`,
  project_id: "p",
  run_id: `r${id}`,
  name: `Dataset ${id}`,
  sample_count: 1,
}));
const Handlers = [
  http.get(`${Prefix}/releases`, () => HttpResponse.json([ReleaseFixture])),
  http.get(`${Prefix}/datasets`, () => HttpResponse.json(Datasets)),
];
beforeAll(() => Server.use(...Handlers));
afterEach(() => {
  cleanup();
  Server.resetHandlers(...Handlers);
});
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ReleaseWorkbench project="p" />
    </QueryClientProvider>,
  );
}
describe("Release workbench", () => {
  it("freezes the explicitly selected dataset and acknowledgement reason", async () => {
    let body: unknown;
    Server.use(
      http.post(`${Prefix}/datasets/d2/releases`, async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(ReleaseFixture);
      }),
    );
    mount();
    await screen.findByRole("option", { name: "Dataset 2 · 1" });
    expect((screen.getByLabelText("数据集") as HTMLSelectElement).value).toBe(
      "",
    );
    fireEvent.change(screen.getByLabelText("数据集"), {
      target: { value: "d2" },
    });
    fireEvent.change(screen.getByLabelText("警告确认原因"), {
      target: { value: "Verified edition" },
    });
    fireEvent.click(screen.getByRole("button", { name: "校验并冻结发布" }));
    await waitFor(() =>
      expect(body).toEqual({ warning_reason: "Verified edition" }),
    );
    expect(
      await screen.findByText("发布被阻断，请修复未通过的门禁后重新发布。"),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "下载 ZIP" })).toBeNull();
  });
  it("previews output before enabling download and clears it when the format changes", async () => {
    Server.use(
      http.get(`${Prefix}/releases`, () =>
        HttpResponse.json([{ ...ReleaseFixture, status: "released" }]),
      ),
      http.post(`${Prefix}/releases/rel:export`, () =>
        HttpResponse.json({
          adapter: "canonical",
          files: { "samples/train.jsonl": "one\ntwo\nthree\nfour\n" },
          issues: [],
        }),
      ),
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: /rel/ }));
    expect(
      (screen.getByRole("button", { name: "下载 ZIP" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "预览前 3 条" }));
    await screen.findByText("samples/train.jsonl");
    expect(screen.queryByText(/four/)).toBeNull();
    expect(
      (screen.getByRole("button", { name: "下载 ZIP" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
    fireEvent.change(screen.getByLabelText("格式"), {
      target: { value: "beir" },
    });
    expect(screen.queryByText("samples/train.jsonl")).toBeNull();
    expect(
      (screen.getByRole("button", { name: "下载 ZIP" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
