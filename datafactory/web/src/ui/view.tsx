import { useEffect, useState } from "react";
import { ApiError } from "../api/client";

type State<T> =
  | { status: "loading" }
  | { status: "empty" }
  | { status: "error"; error: ApiError }
  | { status: "ready"; data: T };

export function useLoad<T>(
  loader: () => Promise<T[]>,
  deps: unknown[],
): State<T[]> {
  const [state, setState] = useState<State<T[]>>({ status: "loading" });
  useEffect(() => {
    let live = true;
    loader()
      .then(
        (data) =>
          live &&
          setState(
            data.length ? { status: "ready", data } : { status: "empty" },
          ),
      )
      .catch((error: ApiError) => live && setState({ status: "error", error }));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

export function View<T>({
  state,
  empty,
  onRetry,
  children,
}: {
  state: State<T>;
  empty: { title: string; action?: string; onAction?: () => void };
  onRetry: () => void;
  children: (data: T) => JSX.Element;
}) {
  if (state.status === "loading")
    return (
      <div className="skeleton" aria-busy="true">
        加载中…
      </div>
    );
  if (state.status === "error") {
    return (
      <div role="alert">
        <p>{state.error.message}</p>
        <button onClick={onRetry}>重试</button>
      </div>
    );
  }
  if (state.status === "empty") {
    return (
      <div>
        <p>{empty.title}</p>
        {empty.action && (
          <button className="primary" onClick={empty.onAction}>
            {empty.action}
          </button>
        )}
      </div>
    );
  }
  return children(state.data);
}
