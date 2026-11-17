import type { Meta, StoryObj } from "@storybook/react-vite";
import { ContentParts } from "./content-parts";

const MetaConfig: Meta<typeof ContentParts> = {
  component: ContentParts,
  title: "Content/Parts",
  args: {
    parts: [
      { type: "text", text: "Frozen evidence\nTraining corpus sample" },
      {
        type: "table",
        html: "<table><caption>Corpus</caption><tr><th>Type</th><th>Count</th></tr><tr><td>Text</td><td>12</td></tr></table>",
      },
    ],
  },
};
export default MetaConfig;
type Story = StoryObj<typeof MetaConfig>;
export const Default: Story = {};
export const Loading: Story = { args: { loading: true } };
export const Empty: Story = { args: { parts: [] } };
export const Error: Story = { args: { error: "Content could not be loaded." } };
export const Dark: Story = { globals: { theme: "dark" } };
