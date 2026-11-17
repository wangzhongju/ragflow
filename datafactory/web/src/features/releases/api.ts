import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";

export const ReleaseKeys = {
  list: (project: string) => ["releases", project] as const,
  datasets: (project: string) => ["datasets", project] as const,
};
export function useReleases(project: string) {
  return useQuery({
    queryKey: ReleaseKeys.list(project),
    queryFn: () => api.releases(project),
  });
}
export function useReleaseDatasets(project: string) {
  return useQuery({
    queryKey: ReleaseKeys.datasets(project),
    queryFn: () => api.datasets(project),
  });
}
export function useCreateRelease(project: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ dataset, reason }: { dataset: string; reason: string }) =>
      api.release(project, dataset, reason),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ReleaseKeys.list(project) }),
  });
}
