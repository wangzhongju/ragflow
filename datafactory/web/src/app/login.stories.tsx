import type { Meta, StoryObj } from "@storybook/react-vite";
import { MemoryRouter } from "react-router-dom";
import { Login } from "./login";

const MetaConfig: Meta<typeof Login> = {
  component: Login,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
};

export default MetaConfig;
export const Default: StoryObj<typeof Login> = {};
