import { useState, type MouseEvent } from "react";
import { useTranslation } from "react-i18next";
import { useSnapshot, useSegments } from "./api";
import { ContentParts } from "../../content/content-parts";
import { StatusBadge } from "../../ui/status-badge";
import "../../styles/workbench.css";

export function SnapshotDetail({
  projectId,
  snapshotId,
}: {
  projectId: string;
  snapshotId: string;
}) {
  const { t } = useTranslation();
  const [cursor, setCursor] = useState<string>();
  const [selected, setSelected] = useState("");
  const snapshot = useSnapshot(projectId, snapshotId);
  const segments = useSegments(projectId, snapshotId, cursor);
  function handleRetry() {
    void snapshot.refetch();
    void segments.refetch();
  }
  function handleSelect(event: MouseEvent<HTMLButtonElement>) {
    setSelected(event.currentTarget.value);
  }
  function handleNext() {
    setCursor(segments.data?.at(-1)?.id);
    setSelected("");
  }
  function handleFirst() {
    setCursor(undefined);
    setSelected("");
  }
  const chosen =
    segments.data?.find((segment) => segment.id === selected) ||
    segments.data?.[0];
  return (
    <section className="page runs-page">
      <header className="page-head">
        <h1>{snapshot.data?.name || t("snapshot")}</h1>
        <button onClick={handleRetry}>{t("refresh")}</button>
      </header>
      {snapshot.isPending && <p aria-busy="true">{t("loading")}</p>}
      {(snapshot.error || segments.error) && (
        <div role="alert">
          <p>{snapshot.error?.message || segments.error?.message}</p>
          <button onClick={handleRetry}>{t("retry")}</button>
        </div>
      )}
      {snapshot.data && (
        <>
          <StatusBadge status={snapshot.data.status} />
          <details>
            <summary>{t("corpusHealth")}</summary>
            <pre className="run-preview">
              {JSON.stringify(snapshot.data.stats, null, 2)}
            </pre>
          </details>
        </>
      )}
      <div className="run-workspace">
        <aside className="run-list">
          {segments.isPending && <p aria-busy="true">{t("loading")}</p>}
          {segments.data?.length === 0 && <p>{t("noSegments")}</p>}
          {segments.data?.map((segment) => (
            <button
              className="run-select"
              key={segment.id}
              value={segment.id}
              aria-pressed={chosen?.id === segment.id}
              onClick={handleSelect}
            >
              <code>{segment.id}</code>
              <span>{segment.title}</span>
              <span>{segment.modality}</span>
            </button>
          ))}
        </aside>
        <article className="run-detail">
          {chosen && (
            <>
              <h2>{chosen.title}</h2>
              <code>
                {chosen.origin.doc_id} / {chosen.origin.chunk_id}
              </code>
              <ContentParts parts={chosen.parts} />
            </>
          )}
        </article>
      </div>
      <div className="row pagination">
        <button disabled={!cursor} onClick={handleFirst}>
          {t("first")}
        </button>
        <button disabled={segments.data?.length !== 100} onClick={handleNext}>
          {t("next")}
        </button>
      </div>
    </section>
  );
}
