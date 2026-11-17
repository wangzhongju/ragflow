import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, type Run, type RunMetrics } from "../../api/client";
import { RunKeys } from "./api";

export function AccountControls({
  project,
  run,
  invocations,
}: {
  project: string;
  run: Run;
  invocations: RunMetrics["invocations"];
}) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const projects = useQuery({
    queryKey: RunKeys.projects(),
    queryFn: api.projects,
  });
  const change = useMutation({
    mutationFn: ({
      kind,
      body,
      id,
    }: {
      kind: "budget" | "bill";
      body: FormData;
      id?: string;
    }) => {
      const reason = String(body.get("reason") || "");
      return kind === "budget"
        ? api.adjustBudget(project, run.id, {
            max_tokens: Number(body.get("tokens")),
            max_invocations: Number(body.get("calls")),
            reason,
          })
        : api.reconcile(project, run.id, id!, {
            actual_tokens: Number(body.get("actual")),
            reason,
          });
    },
    onSuccess: () => {
      void client.invalidateQueries({
        queryKey: RunKeys.allMetrics(project, run.id),
      });
      void client.invalidateQueries({ queryKey: RunKeys.list(project) });
    },
  });
  function handleBudget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    change.mutate({ kind: "budget", body: new FormData(event.currentTarget) });
  }
  function handleReconcile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (window.confirm(t("reconcileConfirm")))
      change.mutate({
        kind: "bill",
        body: new FormData(event.currentTarget),
        id: event.currentTarget.dataset.invocation,
      });
  }
  if (projects.data?.find((item) => item.id === project)?.role !== "owner")
    return null;
  return (
    <details>
      <summary>{t("accountControls")}</summary>
      {change.error && <p role="alert">{change.error.message}</p>}
      {["queued", "paused", "blocked"].includes(run.status) && (
        <form onSubmit={handleBudget} className="run-create">
          <label>
            {t("tokenLimit")}
            <input
              name="tokens"
              type="number"
              min={Math.max(1, run.used_tokens + run.reserved_tokens)}
              max="2147483647"
              defaultValue={run.max_tokens}
              required
            />
          </label>
          <label>
            {t("callLimit")}
            <input
              name="calls"
              type="number"
              min={Math.max(1, run.invocation_count)}
              max="2147483647"
              defaultValue={run.max_invocations}
              required
            />
          </label>
          <label>
            {t("auditReason")}
            <input name="reason" maxLength={2000} required />
          </label>
          <button disabled={change.isPending}>{t("saveBudget")}</button>
        </form>
      )}
      {invocations
        .filter((call) => call.status === "billed_unknown")
        .map((call) => (
          <form
            key={call.id}
            data-invocation={call.id}
            onSubmit={handleReconcile}
            className="run-create"
          >
            <code>{call.id}</code>
            <label>
              {t("actualTokens")}
              <input
                name="actual"
                type="number"
                min="0"
                max="2147483647"
                required
              />
            </label>
            <label>
              {t("auditReason")}
              <input name="reason" maxLength={2000} required />
            </label>
            <button disabled={change.isPending}>{t("reconcileBill")}</button>
          </form>
        ))}
    </details>
  );
}
