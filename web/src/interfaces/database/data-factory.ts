export type FactoryTask = 'embedding' | 'reranker' | 'llm';
export interface ContentPart {
  type: 'text' | 'image' | 'audio' | 'video' | 'structured';
  text?: string;
  asset_id?: string;
  value?: unknown;
}
export interface Evidence {
  id: string;
  text: string;
  parts: ContentPart[];
  split: string;
  name: string;
}
export interface CanonicalSample {
  schema_version: number;
  task: FactoryTask;
  split: string;
  payload: Record<string, any>;
  provenance: Record<string, any>;
}
export interface FactorySample {
  id: number;
  revision: number;
  status: string;
  sample: CanonicalSample;
  evidence: Record<string, Evidence>;
  quality: { code: string; message: string }[];
}
export interface FactoryConfig {
  query_mode: string;
  model_id: string;
  prompt: string;
  questions_per_chunk: number;
  max_samples: number;
  max_calls: number;
  token_budget: number;
  output_tokens: number;
  retrieval: string;
  retrieval_scope: string;
  vector_weight: number;
  threshold: number;
  candidate_count: number;
  knn_top_k: number;
  knn_candidates: number;
  rerank_id: string;
  positive_count: number;
  negative_count: number;
  hard_ratio: number;
  negative_relevance_ceiling: number;
  near_duplicate_threshold: number;
  modalities: string[];
  train_percent: number;
  validation_percent: number;
  seed: number;
}
export interface FactorySummary {
  id: string;
  name: string;
  task: FactoryTask;
  state: string;
}
export interface FactoryDetail extends FactorySummary {
  config: FactoryConfig;
  sources: string[][];
  counts: Record<string, number>;
  error: string;
  captured: number;
  calls: number;
  reserved_tokens: number;
  role: string;
  versions: string[];
  assets: {
    sha: string;
    role: string;
    mime: string;
    name: string;
    doc: string;
    size: number;
  }[];
}
