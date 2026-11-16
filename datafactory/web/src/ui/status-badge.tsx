import { useTranslation } from "react-i18next";

const Icons: Record<string, string> = {
  queued: "◷",
  running: "▶",
  completed: "✓",
  succeeded: "✓",
  paused: "Ⅱ",
  cancelled: "■",
  failed: "!",
  rejected: "!",
  blocked: "!",
  billed_unknown: "?",
  sent: "↗",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <span className="badge run-status" data-status={status}>
      <span aria-hidden="true">{Icons[status] || "•"}</span>
      {t(status)}
    </span>
  );
}
