import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import service from '@/services/data-factory-service';
import {
  FactoryDetail,
  FactorySample,
  FactorySummary,
} from '@/interfaces/database/data-factory';
export const FactoryKeys = {
  all: () => ['data-factory'] as const,
  resource: (path: string, params?: Record<string, unknown>) =>
    ['data-factory', path, params] as const,
};
export function useFactoryResource<T>(
  path: string,
  params?: Record<string, unknown>,
  poll = false,
) {
  return useQuery<T>({
    queryKey: FactoryKeys.resource(path, params),
    queryFn: () => service.read(path, params),
    enabled: Boolean(path),
    refetchInterval: poll ? 3000 : false,
  });
}
export const useInstances = () =>
  useFactoryResource<FactorySummary[]>('/datasets');
export const useInstance = (id: string) =>
  useFactoryResource<FactoryDetail>('/datasets/' + id, undefined, true);
export const useSamples = (id: string, page: number) =>
  useFactoryResource<FactorySample[]>('/datasets/' + id + '/samples', { page });
export function useFactoryAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ path, data }: { path: string; data: unknown }) =>
      service.post(path, data),
    onSuccess: () => client.invalidateQueries({ queryKey: FactoryKeys.all() }),
  });
}
