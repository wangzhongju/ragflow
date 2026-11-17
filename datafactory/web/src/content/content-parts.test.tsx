import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ContentParts } from "./content-parts";
import "../app/providers";

afterEach(cleanup);
describe("Content parts", () => {
  it("preserves table cells while removing executable HTML and remote elements", () => {
    const { container } = render(
      <ContentParts
        parts={[
          {
            type: "table",
            html: '<table onclick="alert(1)"><tr><td colspan="2">Evidence<script>alert(1)</script><img src="https://tracker.invalid/x" onerror="alert(1)"></td></tr></table>',
          },
        ]}
      />,
    );
    expect(screen.getByRole("cell").textContent).toBe("Evidence");
    expect(screen.getByRole("cell").getAttribute("colspan")).toBe("2");
    expect(
      container.querySelector("script, img, [onclick], [onerror]"),
    ).toBeNull();
  });
  it("uses lazy authenticated asset URLs without interpreting text as HTML", () => {
    render(
      <ContentParts
        parts={[
          { type: "image", asset_id: "sha256:abc", text: "Figure" },
          { type: "text", text: "<script>literal</script>" },
        ]}
      />,
    );
    const image = screen.getByRole("img");
    expect(image.getAttribute("src")).toBe(
      "/api/factory/v1/assets/sha256%3Aabc",
    );
    expect(image.getAttribute("loading")).toBe("lazy");
    expect(screen.getByText("<script>literal</script>")).toBeTruthy();
  });
});
