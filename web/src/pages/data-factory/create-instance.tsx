import { useRef, useState } from 'react';
import { v4 as uuid } from 'uuid';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { FactoryConfig, FactoryTask } from '@/interfaces/database/data-factory';
import { useFactoryAction, useFactoryResource } from './hooks';
import { Panel, SelectStyle, TaskNames } from './workbench';

const Fields: {
  key: keyof FactoryConfig;
  label: string;
  step?: number;
  min: number;
  max: number;
}[] = [
  { key: 'questions_per_chunk', label: '每块问题数', min: 1, max: 5 },
  { key: 'max_samples', label: '最多样本数', min: 1, max: 5000 },
  { key: 'max_calls', label: '最多外部调用次数', min: 0, max: 100 },
  { key: 'token_budget', label: 'Token 预留预算', min: 0, max: 200000 },
  { key: 'output_tokens', label: '单次最大输出 Token', min: 64, max: 2048 },
  {
    key: 'vector_weight',
    label: '混合检索向量权重',
    min: 0,
    max: 1,
    step: 0.05,
  },
  { key: 'threshold', label: '相似度阈值', min: 0, max: 1, step: 0.05 },
  { key: 'candidate_count', label: '召回候选数量', min: 2, max: 100 },
  { key: 'knn_top_k', label: '向量 Top K', min: 2, max: 1024 },
  { key: 'knn_candidates', label: '向量候选池', min: 2, max: 4096 },
  { key: 'positive_count', label: '最多正例数', min: 1, max: 20 },
  { key: 'negative_count', label: '目标负例数', min: 1, max: 20 },
  { key: 'hard_ratio', label: '困难负例比例', min: 0, max: 1, step: 0.1 },
  {
    key: 'near_duplicate_threshold',
    label: '近重复阈值',
    min: 0.5,
    max: 1,
    step: 0.05,
  },
  { key: 'train_percent', label: '训练集比例 %', min: 1, max: 98 },
  { key: 'validation_percent', label: '验证集比例 %', min: 1, max: 98 },
  {
    key: 'negative_relevance_ceiling',
    label: '负例相关性上限（Rerank）',
    min: 0,
    max: 1,
    step: 0.05,
  },
  { key: 'seed', label: '分组随机种子', min: 0, max: 2147483647 },
];
type Source = { id: string; name: string };
type Model = {
  model_id: string;
  model_name?: string;
  llm_name?: string;
  model_type: string | string[];
};
export default function CreateInstance({
  defaults,
  onCreated,
}: {
  defaults: FactoryConfig;
  onCreated: (id: string) => void;
}) {
  const [config, setConfig] = useState(defaults);
  const [task, setTask] = useState<FactoryTask>('embedding');
  const [name, setName] = useState('');
  const [sources, setSources] = useState<
    { kb: string; id: string; name: string }[]
  >([]);
  const models = useFactoryResource<Model[]>('/models');
  const action = useFactoryAction();
  const submission = useRef({ signature: '', id: uuid() });
  function change(
    event: React.ChangeEvent<
      HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
    >,
  ) {
    const { name, value, type } = event.target;
    setConfig((previous) => ({
      ...previous,
      [name]: type === 'number' ? Number(value) : value,
    }));
  }
  function changeNumber(key: keyof FactoryConfig, value: number) {
    setConfig((previous) => ({ ...previous, [key]: value }));
  }
  function changeTask(event: React.ChangeEvent<HTMLSelectElement>) {
    setTask(event.target.value as FactoryTask);
  }
  function changeName(event: React.ChangeEvent<HTMLInputElement>) {
    setName(event.target.value);
  }
  function modality(event: React.ChangeEvent<HTMLInputElement>) {
    const { value, checked } = event.target;
    setConfig((previous) => ({
      ...previous,
      modalities: checked
        ? [...previous.modalities, value]
        : previous.modalities.filter((m) => m !== value),
    }));
  }
  function add(kb: string, source: Source) {
    setSources((previous) =>
      previous.some((s) => s.id === source.id)
        ? previous
        : [...previous, { ...source, kb }],
    );
  }
  function remove(event: React.MouseEvent<HTMLButtonElement>) {
    setSources((previous) =>
      previous.filter((s) => s.id !== event.currentTarget.dataset.id),
    );
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const signature = JSON.stringify({ name, task, config, sources });
    if (submission.current.signature !== signature)
      submission.current = { signature, id: uuid() };
    try {
      const result = await action.mutateAsync({
        path: '/datasets',
        data: {
          request_id: submission.current.id,
          name,
          task,
          config,
          sources: sources.map((s) => [s.kb, s.id]),
        },
      });
      onCreated(result.id);
    } catch {
      /* mutation error is displayed below */
    }
  }
  const chat = models.data?.filter((m) => m.model_type.includes('chat')) || [];
  const rerank =
    models.data?.filter((m) => m.model_type.includes('rerank')) || [];
  return (
    <form onSubmit={submit} className="space-y-5 max-w-6xl">
      <h2 className="text-xl font-semibold">创建数据制作实例</h2>
      <section className={Panel}>
        <div className="grid gap-4 md:grid-cols-2">
          <label>
            实例名称
            <Input
              required
              value={name}
              onChange={changeName}
              maxLength={120}
            />
          </label>
          <label>
            生成器
            <select className={SelectStyle} value={task} onChange={changeTask}>
              {Object.entries(TaskNames).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <h3 className="mt-5 mb-3 font-medium">1. 选择已解析文档</h3>
        <SourcePicker onAdd={add} />
        <div className="mt-3 space-y-2">
          {sources.map((s) => (
            <div
              key={s.id}
              className="flex items-center justify-between text-sm"
            >
              <span>{s.name}</span>
              <Button
                type="button"
                variant="outline"
                data-id={s.id}
                onClick={remove}
              >
                移除
              </Button>
            </div>
          ))}
        </div>
      </section>
      <section className={Panel}>
        <h3 className="font-medium mb-4">2. 问题与模型配置</h3>
        <div className="grid gap-4 md:grid-cols-2">
          <label>
            问题来源
            <select
              className={SelectStyle}
              name="query_mode"
              value={config.query_mode}
              onChange={change}
            >
              <option value="existing">复用 Chunk 已有问题</option>
              <option value="template">已有问题 / 模板补充</option>
              <option value="llm">LLM 生成</option>
            </select>
          </label>
          <label>
            生成模型
            <select
              className={SelectStyle}
              name="model_id"
              value={config.model_id}
              onChange={change}
              required={task === 'llm' || config.query_mode === 'llm'}
            >
              <option value="">不调用生成模型</option>
              {chat.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.model_name || m.llm_name || m.model_id}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="block mt-4">
          问题生成提示词
          <Textarea
            name="prompt"
            value={config.prompt}
            onChange={change}
            maxLength={2000}
          />
        </label>
        <p className="text-sm text-text-secondary mt-2">
          LLM
          生成器还会调用所选模型生成有证据的回答。预算按请求上界预留；检索编码和
          Rerank 也计入调用限制。
        </p>
      </section>
      <section className={Panel}>
        <h3 className="font-medium mb-4">3. 候选检索与样本规则</h3>
        <div className="grid gap-4 md:grid-cols-3">
          <label>
            检索方式
            <select
              className={SelectStyle}
              name="retrieval"
              value={config.retrieval}
              onChange={change}
            >
              <option value="lexical">关键词 / BM25</option>
              <option value="vector">向量</option>
              <option value="hybrid">混合</option>
            </select>
          </label>
          <label>
            检索范围
            <select
              className={SelectStyle}
              name="retrieval_scope"
              value={config.retrieval_scope}
              onChange={change}
            >
              <option value="snapshot">当前实例来源文档</option>
              <option value="documents">问题所属文档</option>
            </select>
          </label>
          <label>
            可选 Rerank
            <select
              className={SelectStyle}
              name="rerank_id"
              value={config.rerank_id}
              onChange={change}
            >
              <option value="">不使用 Rerank</option>
              {rerank.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.model_name || m.llm_name || m.model_id}
                </option>
              ))}
            </select>
          </label>
          {Fields.map((field) => (
            <ConfigNumber
              key={field.key}
              field={field}
              value={Number(config[field.key])}
              onUpdate={changeNumber}
            />
          ))}
        </div>
        <div className="flex flex-wrap gap-4 mt-5">
          {['text', 'image', 'audio', 'video', 'structured'].map((value) => (
            <label key={value} className="flex gap-2">
              <input
                type="checkbox"
                value={value}
                checked={config.modalities.includes(value)}
                onChange={modality}
              />
              {value}
            </label>
          ))}
        </div>
        <p className="text-sm text-text-secondary mt-3">
          按文档家族与重复内容分组划分数据集。困难负例不足会显示警告；必须人工确认候选确实不相关。配置随实例固定，调整后创建新实例进行对照。
        </p>
      </section>
      {action.error && <p role="alert">{action.error.message}</p>}
      <Button
        type="submit"
        disabled={
          action.isPending || !sources.length || !config.modalities.length
        }
      >
        {action.isPending ? '正在提交…' : '捕获来源并生成草稿'}
      </Button>
    </form>
  );
}
function ConfigNumber({
  field,
  value,
  onUpdate,
}: {
  field: (typeof Fields)[number];
  value: number;
  onUpdate: (key: keyof FactoryConfig, value: number) => void;
}) {
  function change(event: React.ChangeEvent<HTMLInputElement>) {
    onUpdate(field.key, Number(event.target.value));
  }
  return (
    <label>
      {field.label}
      <Input
        name={field.key}
        type="number"
        min={field.min}
        max={field.max}
        step={field.step || 1}
        value={value}
        onChange={change}
      />
    </label>
  );
}
function SourcePicker({
  onAdd,
}: {
  onAdd: (kb: string, source: Source) => void;
}) {
  const [kb, setKb] = useState('');
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const knowledge = useFactoryResource<Source[]>('/sources', {
    keywords: search,
    page,
  });
  function select(event: React.ChangeEvent<HTMLSelectElement>) {
    setKb(event.target.value);
  }
  function changeSearch(event: React.ChangeEvent<HTMLInputElement>) {
    setSearch(event.target.value);
    setPage(1);
  }
  function next() {
    setPage((p) => p + 1);
  }
  function previous() {
    setPage((p) => p - 1);
  }
  return (
    <div className="space-y-3">
      <Input placeholder="搜索知识库" value={search} onChange={changeSearch} />
      <select className={SelectStyle} value={kb} onChange={select}>
        <option value="">选择知识库</option>
        {knowledge.data?.map((k) => (
          <option key={k.id} value={k.id}>
            {k.name}
          </option>
        ))}
      </select>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          disabled={page === 1}
          onClick={previous}
        >
          上一页知识库
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={(knowledge.data?.length || 0) < 50}
          onClick={next}
        >
          下一页知识库
        </Button>
      </div>
      {kb && <Documents key={kb} kb={kb} onAdd={onAdd} />}
    </div>
  );
}
function Documents({
  kb,
  onAdd,
}: {
  kb: string;
  onAdd: (kb: string, source: Source) => void;
}) {
  const [page, setPage] = useState(1);
  const docs = useFactoryResource<Source[]>('/sources', { kb, page });
  function add(event: React.MouseEvent<HTMLButtonElement>) {
    const doc = docs.data?.find((d) => d.id === event.currentTarget.dataset.id);
    if (doc) onAdd(kb, doc);
  }
  function next() {
    setPage((p) => p + 1);
  }
  function previous() {
    setPage((p) => p - 1);
  }
  return (
    <div className="space-y-2">
      {docs.data?.map((doc) => (
        <div
          key={doc.id}
          className="flex justify-between gap-3 items-center text-sm"
        >
          <span>{doc.name}</span>
          <Button
            type="button"
            variant="outline"
            data-id={doc.id}
            onClick={add}
          >
            选择
          </Button>
        </div>
      ))}
      {!docs.data?.length && (
        <p className="text-text-secondary">没有已完成解析的文档。</p>
      )}
      <div className="flex gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={previous}
          disabled={page === 1}
        >
          上一页文档
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={next}
          disabled={(docs.data?.length || 0) < 50}
        >
          下一页文档
        </Button>
      </div>
    </div>
  );
}
