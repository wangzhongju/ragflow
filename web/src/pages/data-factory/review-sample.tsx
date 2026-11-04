import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  FactorySample,
  ContentPart,
  Evidence,
} from '@/interfaces/database/data-factory';
import { useFactoryAction, useFactoryResource } from './hooks';
import service from '@/services/data-factory-service';
import { Panel, SelectStyle } from './workbench';

export default function ReviewSample({
  dataset,
  row,
}: {
  dataset: string;
  row: FactorySample;
}) {
  const [payload, setPayload] = useState(row.sample.payload);
  const [raw, setRaw] = useState(JSON.stringify(row.sample.payload, null, 2));
  const [reason, setReason] = useState('');
  const [error, setError] = useState('');
  const [browse, setBrowse] = useState(false);
  const action = useFactoryAction();
  const isLLM = row.sample.task === 'llm';
  const query = isLLM
    ? payload.messages.find((m: any) => m.role === 'user')?.content
    : payload.query;
  function update(next: Record<string, any>) {
    setPayload(next);
    setRaw(JSON.stringify(next, null, 2));
  }
  function changeQuery(event: React.ChangeEvent<HTMLTextAreaElement>) {
    const parts = [
      { type: 'text', text: event.target.value },
      ...(query || []).filter((p: ContentPart) => p.type !== 'text'),
    ];
    update(
      isLLM
        ? {
            ...payload,
            messages: payload.messages.map((m: any) =>
              m.role === 'user' ? { ...m, content: parts } : m,
            ),
          }
        : { ...payload, query: parts },
    );
  }
  function changeAnswer(event: React.ChangeEvent<HTMLTextAreaElement>) {
    const index = Number(event.target.dataset.index);
    update({
      ...payload,
      messages: payload.messages.map((m: any, i: number) =>
        i === index
          ? { ...m, content: [{ type: 'text', text: event.target.value }] }
          : m,
      ),
    });
  }
  function label(event: React.ChangeEvent<HTMLSelectElement>) {
    const id = event.target.dataset.id;
    update({
      ...payload,
      candidates: payload.candidates.map((c: any) =>
        c.evidence_id === id
          ? {
              ...c,
              label:
                event.target.value === '' ? null : Number(event.target.value),
            }
          : c,
      ),
    });
  }
  function removeNegative(event: React.MouseEvent<HTMLButtonElement>) {
    const id = event.currentTarget.dataset.id;
    update({
      ...payload,
      negatives: payload.negatives.filter((n: any) => n.evidence_id !== id),
    });
  }
  function promote(event: React.MouseEvent<HTMLButtonElement>) {
    const id = event.currentTarget.dataset.id;
    update({
      ...payload,
      positives: [...payload.positives, id],
      negatives: payload.negatives.filter((n: any) => n.evidence_id !== id),
    });
  }
  function changeReason(event: React.ChangeEvent<HTMLInputElement>) {
    setReason(event.target.value);
  }
  function changeRaw(event: React.ChangeEvent<HTMLTextAreaElement>) {
    setRaw(event.target.value);
  }
  async function applyRaw() {
    setError('');
    try {
      const value = JSON.parse(raw);
      await action.mutateAsync({
        path: '/datasets/' + dataset + '/samples/' + row.id + '/review',
        data: {
          revision: row.revision,
          status: 'draft',
          payload: value,
          reason,
        },
      });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Payload JSON 格式无效');
    }
  }
  function toggleBrowse() {
    setBrowse((value) => !value);
  }
  async function review(event: React.MouseEvent<HTMLButtonElement>) {
    setError('');
    const status = event.currentTarget.dataset.status;
    try {
      await action.mutateAsync({
        path: '/datasets/' + dataset + '/samples/' + row.id + '/review',
        data: { revision: row.revision, status, payload, reason },
      });
    } catch {}
  }
  const text = (parts: ContentPart[]) =>
    parts
      ?.filter((p) => p.type === 'text')
      .map((p) => p.text)
      .join('\n') || '';
  return (
    <article className={Panel}>
      <div className="flex justify-between gap-3">
        <h3 className="font-medium">
          样本 #{row.id} · 修订 {row.revision}
        </h3>
        <span className="text-sm">
          {row.sample.split} · {row.status}
        </span>
      </div>
      <label className="block mt-3">
        问题
        <Textarea value={text(query)} onChange={changeQuery} />
      </label>
      <Parts
        dataset={dataset}
        parts={(query || []).filter((p: ContentPart) => p.type !== 'text')}
      />
      {isLLM &&
        payload.messages.map((message: any, index: number) =>
          message.role === 'assistant' ? (
            <label key={index} className="block mt-3">
              回答
              <Textarea
                data-index={index}
                value={text(message.content)}
                onChange={changeAnswer}
              />
            </label>
          ) : null,
        )}
      <div className="grid gap-3 lg:grid-cols-2 mt-4">
        {Object.entries(row.evidence).map(([id, evidence]) => (
          <details
            key={id}
            className="rounded-lg border border-border-button p-3"
            open
          >
            <summary className="text-sm font-medium">
              {payload.positives?.includes(id)
                ? '正例'
                : payload.negatives?.some((n: any) => n.evidence_id === id)
                  ? '待核实负例'
                  : '证据'}{' '}
              · {evidence.name}
            </summary>
            <p className="text-xs text-text-secondary my-2 break-all">{id}</p>
            <Parts dataset={dataset} parts={evidence.parts} />
            {row.sample.task === 'reranker' && (
              <select
                aria-label="相关性等级"
                className={SelectStyle}
                data-id={id}
                value={
                  payload.candidates.find((c: any) => c.evidence_id === id)
                    ?.label ?? ''
                }
                onChange={label}
              >
                <option value="">未标注</option>
                <option value="0">0 · 不相关</option>
                <option value="1">1 · 部分相关</option>
                <option value="2">2 · 高度相关</option>
              </select>
            )}
            {payload.negatives?.some((n: any) => n.evidence_id === id) && (
              <div className="flex gap-2 mt-3">
                <Button variant="outline" data-id={id} onClick={promote}>
                  改为正例
                </Button>
                <Button variant="outline" data-id={id} onClick={removeNegative}>
                  移除此负例
                </Button>
              </div>
            )}
          </details>
        ))}
      </div>
      <div className="my-3 text-sm text-text-secondary">
        {row.quality.map((issue) => (
          <p key={issue.code + issue.message}>{issue.message}</p>
        ))}
        {row.sample.provenance.warnings?.join('；')}
      </div>
      <Button variant="outline" onClick={toggleBrowse}>
        浏览同分区证据 / 复制引用
      </Button>
      {browse && <EvidenceBrowser dataset={dataset} split={row.sample.split} />}
      <details className="mt-3">
        <summary className="text-sm cursor-pointer">
          高级标注：多正例、媒体配对与多轮对话
        </summary>
        <p className="text-sm text-text-secondary my-2">
          编辑任务 Payload，可引用下方证据 ID 或当前实例资产 ID。媒体使用 type
          与 asset_id；保存时会验证引用和分区。
        </p>
        <Textarea
          className="font-mono min-h-48"
          value={raw}
          onChange={changeRaw}
        />
        <Button variant="outline" onClick={applyRaw}>
          保存 Payload 草稿
        </Button>
      </details>
      <Input
        className="mt-4"
        placeholder="审核备注（驳回时必填）"
        aria-label="审核备注"
        value={reason}
        onChange={changeReason}
      />
      {(error || action.error) && (
        <p role="alert" className="mt-2">
          {error || action.error?.message}
        </p>
      )}
      <div className="flex gap-3 mt-4">
        {[
          ['draft', '保存草稿'],
          ['approved', '批准'],
          ['rejected', '驳回'],
        ].map(([status, name]) => (
          <Button
            key={status}
            variant={status === 'approved' ? 'default' : 'outline'}
            data-status={status}
            onClick={review}
            disabled={action.isPending}
          >
            {name}
          </Button>
        ))}
      </div>
    </article>
  );
}
function EvidenceBrowser({
  dataset,
  split,
}: {
  dataset: string;
  split: string;
}) {
  const [page, setPage] = useState(1);
  const evidence = useFactoryResource<Evidence[]>(
    '/datasets/' + dataset + '/evidence',
    { page },
  );
  function next() {
    setPage((p) => p + 1);
  }
  function previous() {
    setPage((p) => p - 1);
  }
  return (
    <div className="my-3 space-y-2">
      {evidence.data
        ?.filter((e) => e.split === split)
        .map((e) => (
          <details key={e.id}>
            <summary className="text-sm break-all">{e.id}</summary>
            <pre className="whitespace-pre-wrap text-xs">
              {JSON.stringify(e, null, 2)}
            </pre>
          </details>
        ))}
      <Button variant="outline" onClick={previous} disabled={page === 1}>
        上一页证据
      </Button>
      <Button
        variant="outline"
        onClick={next}
        disabled={(evidence.data?.length || 0) < 50}
      >
        下一页证据
      </Button>
    </div>
  );
}
function Parts({ dataset, parts }: { dataset: string; parts: ContentPart[] }) {
  return (
    <div className="space-y-2">
      {parts.map((part, index) =>
        part.type === 'text' ? (
          <p
            key={index}
            className="whitespace-pre-wrap text-sm max-h-56 overflow-auto"
          >
            {part.text}
          </p>
        ) : part.type === 'structured' ? (
          <pre key={index} className="text-xs overflow-auto">
            {JSON.stringify(part.value, null, 2)}
          </pre>
        ) : (
          <Media key={index} dataset={dataset} part={part} />
        ),
      )}
    </div>
  );
}
function Media({ dataset, part }: { dataset: string; part: ContentPart }) {
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  async function load() {
    try {
      setUrl(
        await service.media(
          '/datasets/' + dataset + '/assets/' + part.asset_id,
        ),
      );
    } catch {
      setError('媒体读取失败');
    }
  }
  useEffect(
    () => () => {
      if (url) URL.revokeObjectURL(url);
    },
    [url],
  );
  if (!url)
    return (
      <Button variant="outline" onClick={load}>
        {error || '加载 ' + part.type + ' 预览'}
      </Button>
    );
  if (part.type === 'image')
    return (
      <img
        src={url}
        alt="来源图片"
        className="max-h-80 max-w-full object-contain"
      />
    );
  if (part.type === 'audio') return <audio src={url} controls />;
  return <video src={url} controls className="max-h-80 max-w-full" />;
}
