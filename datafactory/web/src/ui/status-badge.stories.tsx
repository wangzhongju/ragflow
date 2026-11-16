import type { Meta, StoryObj } from "@storybook/react-vite";
import { StatusBadge } from "./status-badge";

const MetaConfig: Meta<typeof StatusBadge> = {
  component: StatusBadge,
  title: "UI/StatusBadge",
  args: { status: "completed" },
};
export default MetaConfig;
type Story = StoryObj<typeof MetaConfig>;
export const Completed: Story = {};
export const Waiting: Story = { args: { status: "queued" } };
export const Partial: Story = { args: { status: "paused" } };
export const Error: Story = { args: { status: "failed" } };
export const UnknownBilling: Story = { args: { status: "billed_unknown" } };
export const Dark: Story = { globals: { theme: "dark" } };
