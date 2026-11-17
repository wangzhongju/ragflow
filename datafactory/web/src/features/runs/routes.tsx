import { useState, type FormEvent, type MouseEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { formatNumber } from "../../lib/format";
import { StatusBadge } from "../../ui/status-badge";
import { RunKeys, useRunControl, useRunMetrics, useRuns } from "./api";
import { AccountControls } from "./account-controls";
import "../../styles/workbench.css";

export function Component() {
  const { projectId = "" } = useParams();
  const [search, setSearch] = useSearchParams();
  const runId = search.get("run") || "";
  const { t, i18n } = useTranslation();
  const client = useQueryClient();
  const runs = useRuns(projectId);
  const recipes = useQuery({
    queryKey: RunKeys.recipes(projectId),
    queryFn: () => api.recipes(projectId),
  });
  const snapshots = useQuery({
    queryKey: RunKeys.snapshots(projectId),
    queryFn: () => api.snapshots(projectId),
  });
  const [formError, setFormError] = useState("");
  const create = useMutation({
    mutationFn: ({
      recipe,
      snapshot,
      limit,
      mode,
    }: {
      recipe: string;
      snapshot: string;
      limit: number;
      mode: string;
    }) =>
      mode === "preview"
        ? api.previewRecipe(projectId, recipe, { snapshot_id: snapshot, limit })
        : api.startRun(projectId, {
            recipe_id: recipe,
            snapshot_id: snapshot,
            limit,
          }),
    onSuccess: (run) => {
      void client.invalidateQueries({ queryKey: RunKeys.list(projectId) });
      setSearch({ run: run.id });
    },
  });
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const recipe = String(data.get("recipe") || "");
    const snapshot = String(data.get("snapshot") || "");
    const mode =
      (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") ||
      "preview";
    const limit = Number(data.get("limit"));
    setFormError("");
    if (!recipe || !snapshot) {
      setFormError(t("missingInputs"));
      return;
    }
    if (mode === "preview" && limit > 50) {
      setFormError(t("previewNote"));
      return;
    }
    create.mutate({ recipe, snapshot, limit, mode });
  }
  function handleSelect(event: MouseEvent<HTMLButtonElement>) {
    setSearch({ run: event.currentTarget.value });
  }
  function handleRefresh() {
    void runs.refetch();
    void recipes.refetch();
    void snapshots.refetch();
    void client.invalidateQueries({ queryKey: ["run-metrics", projectId] });
  }
  function handleLanguage() {
    const lang = i18n.language === "zh" ? "en" : "zh";
    localStorage.setItem("df-language", lang);
    void i18n.changeLanguage(lang);
  }
  function handleTheme() {
    document.documentElement.dataset.theme =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  }
  const inputError = recipes.error || snapshots.error;
  return (
    <section className="page runs-page">
      <header className="page-head">
        <div>
          <h1>{t("runs")}</h1>
          <span className="muted">{t("recent")}</span>
        </div>
        <div className="row">
          <button onClick={handleTheme}>{t("theme")}</button>
          <button onClick={handleLanguage}>{t("language")}</button>
          <button onClick={handleRefresh}>{t("refresh")}</button>
        </div>
      </header>
      <form
        className="run-create"
        onSubmit={handleSubmit}
        aria-label={t("newRun")}
      >
        <label>
          {t("recipe")}
          <select name="recipe" required disabled={recipes.isPending}>
            <option value="">{t("select")}</option>
            {recipes.data?.map((recipe) => (
              <option key={recipe.id} value={recipe.id}>
                {recipe.name} · v{recipe.version}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("snapshot")}
          <select name="snapshot" required disabled={snapshots.isPending}>
            <option value="">{t("select")}</option>
            {snapshots.data
              ?.filter((snapshot) => snapshot.status === "ready")
              .map((snapshot) => (
                <option key={snapshot.id} value={snapshot.id}>
                  {snapshot.name}
                </option>
              ))}
          </select>
        </label>
        <label>
          {t("seedLimit")}
          <input
            name="limit"
            type="number"
            min="1"
            max="500000"
            defaultValue="10"
            required
          />
        </label>
        <div className="row">
          <button
            type="submit"
            value="preview"
            disabled={create.isPending || !!inputError}
          >
            {t("preview")}
          </button>
          <button
            className="primary"
            type="submit"
            value="run"
            disabled={create.isPending || !!inputError}
          >
            {create.isPending ? t("submitting") : t("start")}
          </button>
        </div>
        <p className="muted run-help">{t("previewNote")}</p>
        {(formError || create.error || inputError) && (
          <p role="alert" className="run-help">
            {formError || create.error?.message || inputError?.message}
          </p>
        )}
      </form>
      <div className="run-workspace">
        <aside className="run-list" aria-label={t("runs")}>
          {runs.isPending && <p aria-busy="true">{t("loading")}</p>}
          {runs.error && (
            <div role="alert">
              <p>{runs.error.message}</p>
              <button onClick={handleRefresh}>{t("retry")}</button>
            </div>
          )}
          {runs.data?.length === 0 && <p className="muted">{t("empty")}</p>}
          {runs.data?.map((run) => (
            <button
              key={run.id}
              value={run.id}
              className="run-select"
              aria-pressed={runId === run.id}
              onClick={handleSelect}
            >
              <StatusBadge status={run.status} />
              <code>{run.id}</code>
              <span>
                {t(run.mode)} · {formatNumber(run.sample_count, i18n.language)}{" "}
                {t("samples")}
              </span>
            </button>
          ))}
        </aside>
        {runId ? (
          <RunDetail key={runId} project={projectId} runId={runId} />
        ) : (
          <div className="run-detail empty-panel">{t("chooseRun")}</div>
        )}
      </div>
    </section>
  );
}

function RunDetail({ project, runId }: { project: string; runId: string }) {
  const { t, i18n } = useTranslation();
  const [after, setAfter] = useState<string>();
  const query = useRunMetrics(project, runId, after);
  const control = useRunControl(project);
  function number(value: number) {
    return formatNumber(value, i18n.language);
  }
  function handleRefresh() {
    void query.refetch();
  }
  function handleControl(event: MouseEvent<HTMLButtonElement>) {
    const action = event.currentTarget.value as "pause" | "resume" | "cancel";
    if (action === "cancel" && !window.confirm(t("cancelConfirm"))) return;
    control.mutate({ run: runId, action });
  }
  function handleNext() {
    setAfter(query.data?.next_invocation_cursor || undefined);
  }
  function handleFirst() {
    setAfter(undefined);
  }
  if (query.isPending)
    return (
      <div className="run-detail" aria-busy="true">
        {t("loading")}
      </div>
    );
  if (query.error)
    return (
      <div className="run-detail" role="alert">
        <p>{query.error.message}</p>
        <button onClick={handleRefresh}>{t("retry")}</button>
      </div>
    );
  const { run, checkpoints, invocations } = query.data;
  const active = ["queued", "running"].includes(run.status);
  const paused = ["paused", "blocked"].includes(run.status);
  return (
    <article className="run-detail" aria-label={t("details")}>
      <header className="page-head">
        <StatusBadge status={run.status} />
        <div className="row">
          {active && (
            <button
              value="pause"
              onClick={handleControl}
              disabled={control.isPending}
            >
              {t("pause")}
            </button>
          )}
          {paused && (
            <button
              value="resume"
              onClick={handleControl}
              disabled={control.isPending}
            >
              {t("resume")}
            </button>
          )}
          {(active || paused) && (
            <button
              value="cancel"
              onClick={handleControl}
              disabled={control.isPending}
            >
              {t("cancel")}
            </button>
          )}
        </div>
      </header>
      <p className="run-version">
        {t("version")} <code>{run.recipe_version_id}</code>
      </p>
      {!query.connected && <p role="status">{t("streamLost")}</p>}
      {control.error && <p role="alert">{control.error.message}</p>}
      {run.error && <p role="alert">{run.error}</p>}
      {run.status !== "completed" && <p className="muted">{t("partial")}</p>}
      <label className="run-progress">
        {t("progress")} {number(run.completed_units)} /{" "}
        {number(run.total_units)}
        <progress
          value={run.completed_units}
          max={Math.max(1, run.total_units)}
        />
      </label>
      <ul className="kpis">
        <li>
          <strong>{number(run.sample_count)}</strong>
          <span>{t("samples")}</span>
        </li>
        <li>
          <strong>
            {number(run.used_tokens)} / {number(run.max_tokens)}
          </strong>
          <span>{t("tokens")}</span>
        </li>
        <li>
          <strong>{number(run.reserved_tokens)}</strong>
          <span>{t("reserved")}</span>
        </li>
        <li>
          <strong>
            {number(run.invocation_count)} / {number(run.max_invocations)}
          </strong>
          <span>{t("calls")}</span>
        </li>
      </ul>
      <AccountControls project={project} run={run} invocations={invocations} />
      <h2>{t("timeline")}</h2>
      {checkpoints.length === 0 ? (
        <p className="muted">{t("noCheckpoints")}</p>
      ) : (
        <div className="run-table">
          <table>
            <thead>
              <tr>
                <th>{t("column")}</th>
                <th>{t("batches")}</th>
                <th>{t("rows")}</th>
                <th>{t("duration")}</th>
              </tr>
            </thead>
            <tbody>
              {checkpoints.map((point) => (
                <tr key={point.stage}>
                  <td>
                    <code>{point.column}</code>
                    <meter
                      min="0"
                      max={Math.max(
                        1,
                        ...checkpoints.map((item) => item.elapsed_ms),
                      )}
                      value={point.elapsed_ms}
                      aria-label={point.column}
                    />
                  </td>
                  <td>{number(point.batches)}</td>
                  <td>{number(point.rows)}</td>
                  <td>{number(point.elapsed_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2>{t("invocations")}</h2>
      <p className="muted">{t("unknownBilling")}</p>
      {invocations.length === 0 ? (
        <p className="muted">{t("noCalls")}</p>
      ) : (
        <div className="run-table">
          <table>
            <thead>
              <tr>
                <th>{t("column")}</th>
                <th>{t("model")}</th>
                <th>{t("status")}</th>
                <th>{t("row")}</th>
              </tr>
            </thead>
            <tbody>
              {invocations.map((call) => (
                <tr key={call.id}>
                  <td>{call.column}</td>
                  <td>
                    <code>{call.model_id}</code>
                    <small>{call.model_fingerprint}</small>
                  </td>
                  <td>
                    <StatusBadge status={call.status} />
                    {call.error && <p role="alert">{call.error}</p>}
                  </td>
                  <td>
                    <code className="row-key">{call.row_key}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="row pagination">
        <button onClick={handleFirst} disabled={!after}>
          {t("first")}
        </button>
        <button
          onClick={handleNext}
          disabled={!query.data.next_invocation_cursor}
        >
          {t("next")}
        </button>
      </div>
      {run.mode === "preview" && (
        <>
          <h2>{t("previewResults")}</h2>
          <pre className="run-preview">
            {JSON.stringify(run.preview, null, 2)}
          </pre>
        </>
      )}
    </article>
  );
}
