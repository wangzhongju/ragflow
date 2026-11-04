import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useFactoryResource, useInstances } from './hooks';
import { FactoryConfig, FactoryTask } from '@/interfaces/database/data-factory';
import CreateInstance from './create-instance';
import Instance from './instance';

export interface Capabilities {
  enabled: boolean;
  defaults: FactoryConfig;
  adapters: {
    id: string;
    name: string;
    tasks: string[];
    modalities: string[];
  }[];
}
export const TaskNames = {
  embedding: 'Embedding',
  reranker: 'Reranker',
  llm: 'LLM',
};
export const Panel = 'rounded-xl border border-border-button bg-bg-card p-5';
export const SelectStyle =
  'w-full rounded-md border border-border-button bg-bg-base px-3 py-2 text-text-primary';
export default function Workbench() {
  const capability = useFactoryResource<Capabilities>('/capabilities');
  if (capability.isPending)
    return <div className="p-8">正在连接数据制作服务…</div>;
  if (!capability.data?.enabled)
    return (
      <div className="p-8 text-text-secondary">
        数据制作服务未启用或暂不可用。知识库、聊天等功能可继续使用。
      </div>
    );
  return <Workspace capability={capability.data} />;
}
function Workspace({ capability }: { capability: Capabilities }) {
  const instances = useInstances();
  const [selected, setSelected] = useState('');
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState('');
  function select(event: React.MouseEvent<HTMLButtonElement>) {
    setSelected(event.currentTarget.dataset.id || '');
    setCreating(false);
  }
  function create() {
    setCreating(true);
  }
  function created(id: string) {
    setSelected(id);
    setCreating(false);
  }
  function search(event: React.ChangeEvent<HTMLInputElement>) {
    setFilter(event.target.value);
  }
  return (
    <div className="flex h-full min-h-0 w-full text-text-primary">
      <aside className="w-64 shrink-0 overflow-y-auto border-r border-border-button p-4 space-y-4">
        <h1 className="text-xl font-semibold">数据制作</h1>
        <p className="text-sm text-text-secondary">
          从知识库证据到可追溯、可审核的数据集。
        </p>
        <Button onClick={create} className="w-full">
          创建实例
        </Button>
        <Input
          aria-label="筛选实例"
          placeholder="筛选实例"
          value={filter}
          onChange={search}
        />
        {instances.data
          ?.filter((item) => item.name.includes(filter))
          .map((item) => (
            <button
              key={item.id}
              data-id={item.id}
              onClick={select}
              className={
                'block w-full rounded-lg p-3 text-left ' +
                (selected === item.id && !creating
                  ? 'bg-bg-base border border-border-button'
                  : '')
              }
            >
              <div className="truncate font-medium">{item.name}</div>
              <div className="text-xs text-text-secondary">
                {TaskNames[item.task as FactoryTask]} · {item.state}
              </div>
            </button>
          ))}
      </aside>
      <main className="min-w-0 flex-1 overflow-y-auto p-6 space-y-5">
        {creating ? (
          <CreateInstance defaults={capability.defaults} onCreated={created} />
        ) : selected ? (
          <Instance
            key={selected}
            id={selected}
            adapters={capability.adapters}
          />
        ) : (
          <div className={Panel}>
            <h2 className="text-lg font-medium">
              选择生成器，复用同一套数据基础设施
            </h2>
            <div className="grid gap-4 lg:grid-cols-3 mt-5">
              {Object.entries(TaskNames).map(([key, name]) => (
                <div key={key} className={Panel}>
                  <h3>{name}</h3>
                  <p className="text-sm text-text-secondary mt-2">
                    {key === 'embedding'
                      ? '问题、多正例与困难负例'
                      : key === 'reranker'
                        ? '候选集合与相关性分级'
                        : '有证据的指令与对话样本'}
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-5 text-sm text-text-secondary">
              生成草稿 → 人工审核 → 质量检查 → 冻结版本 →
              按训练框架导出。训练与模型评估在外部执行。
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
