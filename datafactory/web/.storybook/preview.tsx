import type { Preview } from "@storybook/react-vite";
import { Providers } from "../src/app/providers";
import "../src/styles/tokens.css";

const PreviewConfig: Preview = {
  globalTypes: {
    theme: { toolbar: { icon: "circlehollow", items: ["light", "dark"] } },
  },
  initialGlobals: { theme: "light" },
  decorators: [
    (Story, context) => {
      document.documentElement.dataset.theme = context.globals.theme;
      return (
        <Providers>
          <Story />
        </Providers>
      );
    },
  ],
};
export default PreviewConfig;
