import { FactoryConfig, FactoryTask } from '@/interfaces/database/data-factory';
export interface CreateFactoryDataset {
  request_id: string;
  name: string;
  task: FactoryTask;
  sources: string[][];
  config: FactoryConfig;
}
export interface ReviewFactorySample {
  revision: number;
  status: string;
  reason: string;
  payload: Record<string, any>;
}
