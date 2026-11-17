import { expect, test } from "@playwright/test";

test("the factory entry returns to sign-in when the stored RAGFlow token is rejected", async ({
  page,
}) => {
  await page.goto("/factory/login");
  await page.evaluate(() => localStorage.setItem("Authorization", "expired"));

  const submittedTokens: (string | null)[] = [];
  await page.route("**/api/factory/v1/me", async (route) => {
    submittedTokens.push(await route.request().headerValue("authorization"));
    await route.fulfill({
      status: 401,
      json: { code: "unauthorized", message: "Sign in again." },
    });
  });
  const reloads: string[] = [];
  page.on("request", (request) => {
    if (
      request.isNavigationRequest() &&
      request.url().endsWith("/factory/login")
    ) {
      reloads.push(request.url());
    }
  });

  await page.goto("/factory/");
  await expect(page).toHaveURL(/\/factory\/login$/);
  await expect(
    page.getByRole("heading", { name: "登录 DataFactory" }),
  ).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("Authorization"))).toBe(
    "expired",
  );
  expect(submittedTokens).toEqual(["expired"]);
  expect(reloads).toEqual([]);
});
