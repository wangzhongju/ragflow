import { useState, type FormEvent, type MouseEvent } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "../../api/client";
import { StatusBadge } from "../../ui/status-badge";
import { useCreateRelease, useReleaseDatasets, useReleases } from "./api";
import "../../styles/workbench.css";

const Adapters = [
  "canonical",
  "beir",
  "sentence_transformers",
  "flagembedding",
];
export function ReleaseWorkbench({ project }: { project: string }) {
  const { t } = useTranslation();
  const releases = useReleases(project);
  const datasets = useReleaseDatasets(project);
  const create = useCreateRelease(project);
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const [adapter, setAdapter] = useState("canonical");
  const release = releases.data?.find((item) => item.id === selected);
  const preview = useMutation({
    mutationFn: () => api.export(project, selected, adapter),
  });
  const download = useMutation({
    mutationFn: () => api.downloadPackage(project, selected, adapter),
    onSuccess: (data) => {
      const url = URL.createObjectURL(data);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${selected}-${adapter}.zip`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate(
      {
        dataset: String(form.get("dataset")),
        reason: String(form.get("reason") || ""),
      },
      {
        onSuccess: (result) => {
          setSelected(result.id);
          preview.reset();
          download.reset();
        },
      },
    );
  }
  function handleSelect(event: MouseEvent<HTMLButtonElement>) {
    setSelected(event.currentTarget.value);
    preview.reset();
    download.reset();
  }
  function handleAdapter(event: FormEvent<HTMLSelectElement>) {
    setAdapter(event.currentTarget.value);
    preview.reset();
    download.reset();
  }
  function handlePreview() {
    preview.mutate();
  }
  function handleDownload() {
    download.mutate();
  }
  function handleRefresh() {
    void releases.refetch();
    void datasets.refetch();
  }
  function handleNext() {
    setOffset(offset + 50);
  }
  function handlePrevious() {
    setOffset(Math.max(0, offset - 50));
  }
  const error =
    releases.error ||
    datasets.error ||
    create.error ||
    preview.error ||
    download.error;
  return (
    <section className="page runs-page">
      <header className="page-head">
        <h1>{t("releasesTitle")}</h1>
        <button onClick={handleRefresh}>{t("refresh")}</button>
      </header>
      <form className="run-create" onSubmit={handleCreate}>
        <label>
          {t("dataset")}
          <select name="dataset" required defaultValue="">
            <option value="">{t("chooseDataset")}</option>
            {datasets.data?.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {item.sample_count}
              </option>
            ))}
          </select>
        </label>
        <label>
          {t("warningReason")}
          <input name="reason" maxLength={2000} />
        </label>
        <button
          disabled={
            create.isPending ||
            preview.isPending ||
            download.isPending ||
            !datasets.data?.length
          }
        >
          {t("freezeRelease")}
        </button>
      </form>
      {(releases.isPending || datasets.isPending) && (
        <p aria-busy="true">{t("loading")}</p>
      )}
      {error && (
        <div role="alert">
          <p>{error.message}</p>
          <button onClick={handleRefresh}>{t("retry")}</button>
        </div>
      )}
      {releases.data?.length === 0 && (
        <div className="empty-panel">{t("noReleases")}</div>
      )}
      <div className="run-workspace">
        <aside className="run-list" aria-label={t("releasesTitle")}>
          {releases.data?.slice(offset, offset + 50).map((item) => (
            <button
              className="run-select"
              key={item.id}
              value={item.id}
              disabled={
                create.isPending || preview.isPending || download.isPending
              }
              aria-pressed={selected === item.id}
              onClick={handleSelect}
            >
              <code>{item.id}</code>
              <StatusBadge status={item.status} />
              <span>
                {item.sample_count} {t("samplesUnit")}
              </span>
            </button>
          ))}
          <div className="row">
            <button onClick={handlePrevious} disabled={offset === 0}>
              {t("previous")}
            </button>
            <button
              onClick={handleNext}
              disabled={!releases.data || releases.data.length <= offset + 50}
            >
              {t("next")}
            </button>
          </div>
        </aside>
        <article className="run-detail">
          {!release ? (
            <div className="empty-panel">{t("chooseRelease")}</div>
          ) : (
            <>
              <h2>{release.id}</h2>
              <StatusBadge status={release.status} />
              {release.status === "blocked" && (
                <p role="status">{t("releaseBlocked")}</p>
              )}
              <table>
                <thead>
                  <tr>
                    <th>{t("gate")}</th>
                    <th>{t("status")}</th>
                    <th>{t("detail")}</th>
                  </tr>
                </thead>
                <tbody>
                  {release.gates.map((gate) => (
                    <tr key={gate.name}>
                      <td>
                        {t(gate.name)} · {t(gate.level)}
                      </td>
                      <td>{gate.passed ? t("passed") : t("failed")}</td>
                      <td>{gate.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <details>
                <summary>{t("manifest")}</summary>
                <pre className="run-preview">
                  {JSON.stringify(release.manifest, null, 2)}
                </pre>
              </details>
              {release.status === "released" && (
                <section>
                  <h2>{t("exportPackage")}</h2>
                  <p>{t("packageContents")}</p>
                  <label>
                    {t("adapter")}
                    <select
                      value={adapter}
                      onChange={handleAdapter}
                      disabled={preview.isPending || download.isPending}
                    >
                      {Adapters.map((name) => (
                        <option key={name}>{name}</option>
                      ))}
                    </select>
                  </label>
                  <div className="row">
                    <button
                      onClick={handlePreview}
                      disabled={preview.isPending}
                    >
                      {t("previewExport")}
                    </button>
                    <button
                      onClick={handleDownload}
                      disabled={download.isPending || !preview.data}
                    >
                      {t("downloadPackage")}
                    </button>
                  </div>
                  {preview.isPending && <p aria-busy="true">{t("loading")}</p>}
                  {preview.data &&
                    Object.entries(preview.data.files).map(
                      ([name, content]) => (
                        <div key={name}>
                          <h3>{name}</h3>
                          <pre className="run-preview">
                            {content.split("\n").slice(0, 3).join("\n")}
                          </pre>
                        </div>
                      ),
                    )}
                </section>
              )}
            </>
          )}
        </article>
      </div>
    </section>
  );
}
