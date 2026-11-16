import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, watchRun, type Run } from "../../api/client";

export const RunKeys = {
  list: (project: string) => ["runs", project] as const,
  metrics: (project: string, run: string, after?: string) =>
    ["run-metrics", project, run, after] as const,
  recipes: (project: string) => ["recipes", project] as const,
  snapshots: (project: string) => ["snapshots", project] as const,
};

export function useRuns(project: string) {
  return useQuery({
    queryKey: RunKeys.list(project),
    queryFn: () => api.runs(project),
    refetchInterval: 10000,
  });
}

export function useRunMetrics(project: string, run: string, after?: string) {
  const client = useQueryClient();
  const [connected, setConnected] = useState(true);
  const query = useQuery({
    queryKey: RunKeys.metrics(project, run, after),
    queryFn: () => api.runMetrics(project, run, after),
    enabled: !!run,
    refetchInterval: connected ? false : 5000,
  });
  const active =
    !!run &&
    (!query.data || ["queued", "running"].includes(query.data.run.status));
  useEffect(() => {
    if (!active) return;
    setConnected(true);
    return watchRun(
      project,
      run,
      (record) => {
        client.setQueryData<Run[]>(RunKeys.list(project), (current) =>
          current?.map((item) => (item.id === record.id ? record : item)),
        );
        void client.invalidateQueries({
          queryKey: ["run-metrics", project, run],
        });
      },
      setConnected,
    );
  }, [project, run, active, client]);
  return { ...query, connected: connected || !active };
}

export function useRunControl(project: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      run,
      action,
    }: {
      run: string;
      action: "pause" | "resume" | "cancel";
    }) => {
      const commands = {
        pause: api.pauseRun,
        resume: api.resumeRun,
        cancel: api.cancelRun,
      };
      return commands[action](project, run);
    },
    onSuccess: (run) => {
      void client.invalidateQueries({ queryKey: RunKeys.list(project) });
      void client.invalidateQueries({
        queryKey: ["run-metrics", project, run.id],
      });
    },
  });
}
