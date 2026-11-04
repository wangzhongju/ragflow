import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  useFactoryAction,
  useFactoryResource,
  useInstance,
  useSamples,
} from './hooks';
import { Capabilities, Panel, SelectStyle, TaskNames } from './workbench';
import service from '@/services/data-factory-service';
import ReviewSample from './review-sample';

export default function Instance({
  id,
  adapters,
}: {
  id: string;
  adapters: Capabilities['adapters'];
}) {
  const query = useInstance(id);
  const action = useFactoryAction();
  const [tab, setTab] = useState('samples');
  const [adapter, setAdapter] = useState('canonical-v2');
  const [version, setVersion] = useState('');
  const [error, setError] = useState('');
  function changeTab(event: React.MouseEvent<HTMLButtonElement>) {
    setTab(event.currentTarget.dataset.tab || 'samples');
  }
  function changeAdapter(event: React.ChangeEvent<HTMLSelectElement>) {
    setAdapter(event.target.value);
  }
  function changeVersion(event: React.ChangeEvent<HTMLSelectElement>) {
    setVersion(event.target.value);
  }
  async function control(event: React.MouseEvent<HTMLButtonElement>) {
    const operation = event.currentTarget.dataset.action;
    try {
      await action.mutateAsync({
        path: '/datasets/' + id + '/jobs/' + operation,
        data: {},
      });
    } catch {}
  }
  async function freeze() {
    try {
      const result = await action.mutateAsync({
        path: '/datasets/' + id + '/versions',
        data: {},
      });
      setVersion(result.version);
    } catch {}
  }
  async function download() {
    setError('');
    try {
      await service.download(
        '/datasets/' +
          id +
          '/versions/' +
          (version || query.data?.versions[0]) +
          '/download?adapter=' +
          adapter,
        'dataset-' + adapter + '.zip',
      );
    } catch (exc) {
      setError(String(exc));
    }
  }
  if (!query.data) return <p>{query.error?.message || '正在读取实例…'}</p>;
  const data = query.data;
  return (
    <>
      <section className={Panel}>
        <h2 className="text-xl font-semibold">{data.name}</h2>
        <p className="mt-2 text-text-secondary">
          {TaskNames[data.task]} · {data.state} · 已捕获 {data.captured}/
          {data.sources.length} 个文档 · 调用 {data.calls}/
          {data.config.max_calls} · 已预留 {data.reserved_tokens}/
          {data.config.token_budget} Token
        </p>
        <p className="text-sm mt-2">
          草稿 {data.counts.draft || 0} · 已批准 {data.counts.approved || 0} ·
          已驳回 {data.counts.rejected || 0}
        </p>
        {data.error && (
          <p role="alert" className="mt-2">
            {data.error}
          </p>
        )}
        <div className="flex flex-wrap gap-3 mt-4">
          {['queued', 'running'].includes(data.state) && (
            <Button
              variant="outline"
              data-action="cancel"
              onClick={control}
              disabled={action.isPending}
            >
              取消生成
            </Button>
          )}
          {['failed', 'cancelled', 'interrupted'].includes(data.state) && (
            <Button
              variant="outline"
              data-action="retry"
              onClick={control}
              disabled={action.isPending}
            >
              从检查点继续
            </Button>
          )}
          {[
            ['samples', '样本审核'],
            ['quality', '质量检查'],
            ['sources', '来源与资产'],
            ['config', '配置与权限'],
          ].map(([value, label]) => (
            <Button
              key={value}
              variant={tab === value ? 'default' : 'outline'}
              data-tab={value}
              onClick={changeTab}
            >
              {label}
            </Button>
          ))}
        </div>
      </section>
      {(action.error || error) && (
        <p role="alert">{action.error?.message || error}</p>
      )}
      {tab === 'samples' && (
        <Samples
          key={String(data.counts.draft) + String(data.counts.approved)}
          id={id}
        />
      )}
      {tab === 'quality' && <Quality id={id} />}
      {tab === 'sources' && (
        <section className={Panel}>
          <h3 className="font-medium mb-3">
            资产按内容哈希去重，原件与派生关系随版本导出
          </h3>
          <div className="space-y-2">
            {data.assets.map((a, index) => (
              <div key={a.sha + index} className="text-sm break-all">
                {a.role} · {a.name} · {a.mime} · {(a.size / 1024).toFixed(1)}{' '}
                KiB · {a.sha}
              </div>
            ))}
          </div>
        </section>
      )}
      {tab === 'config' && (
        <>
          <details open className={Panel}>
            <summary>固定的生成配置</summary>
            <pre className="overflow-x-auto text-sm mt-3">
              {JSON.stringify(data.config, null, 2)}
            </pre>
          </details>
          <Membership id={id} role={data.role} />
        </>
      )}
      <section className={Panel}>
        <h3 className="font-medium mb-3">冻结与导出</h3>
        <p className="text-sm text-text-secondary mb-3">
          只有通过质量检查并批准的样本进入版本。后续修订不会改变已有版本。ZIP
          包包含分区数据、来源、媒体和校验清单。
        </p>
        <div className="grid gap-3 lg:grid-cols-3">
          <select
            aria-label="导出适配器"
            className={SelectStyle}
            value={adapter}
            onChange={changeAdapter}
          >
            {adapters
              .filter((a) => a.tasks.includes(data.task))
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
          <select
            aria-label="冻结版本"
            className={SelectStyle}
            value={version || data.versions[0] || ''}
            onChange={changeVersion}
          >
            <option value="" disabled>
              尚无版本
            </option>
            {data.versions.map((v) => (
              <option key={v} value={v}>
                {v.slice(0, 16)}
              </option>
            ))}
          </select>
          <div className="flex gap-2">
            <Button
              onClick={freeze}
              disabled={
                data.state !== 'ready' ||
                !data.counts.approved ||
                action.isPending ||
                data.role === 'reviewer'
              }
            >
              冻结已批准样本
            </Button>
            <Button
              variant="outline"
              onClick={download}
              disabled={!data.versions.length || data.role === 'reviewer'}
            >
              下载 ZIP
            </Button>
          </div>
        </div>
      </section>
    </>
  );
}
function Samples({ id }: { id: string }) {
  const [page, setPage] = useState(1);
  const samples = useSamples(id, page);
  function next() {
    setPage((p) => p + 1);
  }
  function previous() {
    setPage((p) => p - 1);
  }
  return (
    <div className="space-y-4">
      {samples.data?.map((row) => (
        <ReviewSample
          key={row.id + ':' + row.revision}
          dataset={id}
          row={row}
        />
      ))}
      {!samples.data?.length && (
        <p className="text-text-secondary">任务完成后，草稿会显示在这里。</p>
      )}
      <div className="flex gap-3">
        <Button variant="outline" onClick={previous} disabled={page === 1}>
          上一页
        </Button>
        <span>第 {page} 页</span>
        <Button
          variant="outline"
          onClick={next}
          disabled={(samples.data?.length || 0) < 20}
        >
          下一页
        </Button>
      </div>
    </div>
  );
}
function Quality({ id }: { id: string }) {
  const report = useFactoryResource<{
    total: number;
    blocked: number;
    approved: number;
    samples: {
      id: number;
      issues: { message: string }[];
      warnings: string[];
    }[];
  }>('/datasets/' + id + '/quality');
  return (
    <section className={Panel}>
      <h3 className="font-medium">质量检查</h3>
      <p className="mt-3">
        总样本 {report.data?.total} · 阻止发布 {report.data?.blocked} · 已批准{' '}
        {report.data?.approved}
      </p>
      <p className="text-sm text-text-secondary mt-2">
        检查结构、来源、分区、正负冲突、重复与敏感密钥。相关性与答案正确性仍需人工判断。Recall、MRR、NDCG、编码性能应在外部模型评测中计算。
      </p>
      {report.data?.samples
        .filter((s) => s.issues.length || s.warnings.length)
        .map((s) => (
          <p key={s.id} className="mt-3 text-sm">
            #{s.id}：{s.issues.map((i) => i.message).join('；')}{' '}
            {s.warnings.join('；')}
          </p>
        ))}
    </section>
  );
}
function Membership({ id, role }: { id: string; role: string }) {
  const [user, setUser] = useState('');
  const [targetRole, setTargetRole] = useState('reviewer');
  const action = useFactoryAction();
  function changeUser(e: React.ChangeEvent<HTMLInputElement>) {
    setUser(e.target.value);
  }
  function changeRole(e: React.ChangeEvent<HTMLSelectElement>) {
    setTargetRole(e.target.value);
  }
  async function save() {
    try {
      await action.mutateAsync({
        path: '/datasets/' + id + '/members',
        data: { user, role: targetRole },
      });
    } catch {}
  }
  return (
    <section className={Panel}>
      <h3 className="font-medium">团队审核权限</h3>
      <p className="text-sm text-text-secondary my-3">
        只允许已有 RAGFlow 团队成员，且每次访问仍检查来源权限。
      </p>
      <div className="flex gap-3">
        <Input
          aria-label="团队成员 ID"
          placeholder="团队成员 ID"
          value={user}
          onChange={changeUser}
        />
        <select
          className={SelectStyle}
          value={targetRole}
          onChange={changeRole}
        >
          <option value="reviewer">审核者</option>
          <option value="publisher">发布者</option>
          <option value="remove">移除授权</option>
        </select>
        <Button
          onClick={save}
          disabled={role !== 'owner' || !user || action.isPending}
        >
          保存授权
        </Button>
      </div>
      {action.error && <p role="alert">{action.error.message}</p>}
      {action.isSuccess && <p>授权已更新。</p>}
    </section>
  );
}
