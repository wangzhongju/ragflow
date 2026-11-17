import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";

export const CorpusKeys = {
  snapshot: (project: string, snapshot: string) =>
    ["snapshot", project, snapshot] as const,
  segments: (project: string, snapshot: string, after?: string) =>
    ["segments", project, snapshot, after] as const,
};
export function useSnapshot(project: string, snapshot: string) {
  return useQuery({
    queryKey: CorpusKeys.snapshot(project, snapshot),
    queryFn: () => api.snapshot(project, snapshot),
  });
}
export function useSegments(project: string, snapshot: string, after?: string) {
  return useQuery({
    queryKey: CorpusKeys.segments(project, snapshot, after),
    queryFn: () => api.segments(project, snapshot, after),
  });
}
