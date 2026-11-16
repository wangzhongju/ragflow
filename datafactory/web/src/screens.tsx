import { FormEvent, useEffect, useState } from "react";
import {
  Link,
  NavLink,
  Outlet,
  useNavigate,
  useParams,
} from "react-router-dom";
import { Base64 } from "js-base64";
import JSEncrypt from "jsencrypt";
import {
  Dataset,
  OverviewCounts,
  RagflowDataset,
  api,
  login,
} from "./api/client";
import { StatusBadge } from "./ui/status-badge";
import { View, useLoad } from "./ui/view";

const RAGFLOW_PUBLIC_KEY =
  "-----BEGIN PUBLIC KEY-----MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArq9XTUSeYr2+N1h3Afl/z8Dse/2yD0ZGrKwx+EEEcdsBLca9Ynmx3nIB5obmLlSfmskLpBo0UACBmB5rEjBp2Q2f3AG3Hjd4B+gNCG6BDaawuDlgANIhGnaTLrIqWrrcm4EMzJOnAOI1fgzJRsOOUEfaS318Eq9OVO3apEyCCt0lOQK6PuksduOjVxtltDav+guVAA068NrPYmRNabVKRNLJpL8w4D44sfth5RvZ3q9t+6RTArpEtc5sh5ChzvqPOzKGMXW83C95TxmXqpbK6olN4RevSfVjEAgCydH6HN6OhtOQEcnrU97r9H0iZOWwbw3pVrZiUkuRD1R56Wzs2wIDAQAB-----END PUBLIC KEY-----";

function encryptPassword(password: string): string {
  const encryptor = new JSEncrypt();
  encryptor.setPublicKey(RAGFLOW_PUBLIC_KEY);
  return encryptor.encrypt(Base64.encode(password)) || "";
}

export function Shell() {
  return (
    <div className="frame">
      <header className="topbar">
        <strong>DataFactory</strong>
        <span className="muted">数据制作平台</span>
      </header>
      <div className="body">
        <Outlet />
      </div>
    </div>
  );
}

export function Login() {
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      await login(
        String(data.get("email")),
        encryptPassword(String(data.get("password"))),
      );
      navigate("/projects");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="login" onSubmit={handleSubmit}>
      <h1>登录 DataFactory</h1>
      <p className="muted">使用 RAGFlow 账号登录。平台不保存密码。</p>
      <label>
        邮箱
        <input name="email" type="email" required autoComplete="username" />
      </label>
      <label>
        密码
        <input
          name="password"
          type="password"
          required
          autoComplete="current-password"
        />
      </label>
      {error && <p role="alert">{error}</p>}
      <button className="primary" type="submit" disabled={busy}>
        {busy ? "登录中…" : "登录"}
      </button>
    </form>
  );
}

export function Projects() {
  const [tick, setTick] = useState(0);
  const state = useLoad(() => api.projects(), [tick]);

  async function handleCreate() {
    const name = window.prompt("项目名称");
    if (!name) return;
    await api.createProject(name);
    setTick((n) => n + 1);
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>项目</h1>
        <button className="primary" onClick={handleCreate}>
          新建项目
        </button>
      </header>
      <View
        state={state}
        onRetry={() => setTick((n) => n + 1)}
        empty={{
          title: "还没有项目。",
          action: "新建项目",
          onAction: handleCreate,
        }}
      >
        {(projects) => (
          <ul className="cards">
            {projects.map((project) => (
              <li key={project.id}>
                <Link to={`/projects/${project.id}`}>
                  <strong>{project.name}</strong>
                  <span className="muted">
                    {project.role === "owner" ? "所有者" : project.role}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </View>
    </section>
  );
}

const NAV = [
  { to: "", label: "概览", end: true },
  { to: "snapshots", label: "语料" },
  { to: "runs", label: "运行" },
  { to: "datasets", label: "数据集" },
  { to: "review", label: "审核" },
  { to: "releases", label: "发布" },
];

export function ProjectLayout() {
  const { projectId = "" } = useParams();
  const [counts, setCounts] = useState<OverviewCounts | null>(null);

  useEffect(() => {
    api
      .overview(projectId)
      .then(setCounts)
      .catch(() => setCounts(null));
  }, [projectId]);

  return (
    <div className="project">
      <nav className="side">
        <Link className="back" to="/projects">
          ‹ 全部项目
        </Link>
        {NAV.map((item) => (
          <NavLink key={item.label} to={item.to} end={item.end}>
            {item.label}
            {item.to === "review" && counts?.pending_reviews ? (
              <em>{counts.pending_reviews}</em>
            ) : null}
          </NavLink>
        ))}
      </nav>
      <Outlet />
    </div>
  );
}

export function Overview() {
  const { projectId = "" } = useParams();
  const [counts, setCounts] = useState<OverviewCounts | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .overview(projectId)
      .then(setCounts)
      .catch((err) => setError(err.message));
  }, [projectId]);

  if (error)
    return (
      <section className="page">
        <p role="alert">{error}</p>
      </section>
    );
  if (!counts)
    return (
      <section className="page">
        <div className="skeleton" aria-busy="true">
          加载中…
        </div>
      </section>
    );

  const cards = [
    { label: "样本", value: counts.samples },
    { label: "数据集", value: counts.datasets },
    { label: "待审核", value: counts.pending_reviews },
    { label: "运行中", value: counts.running },
    { label: "已发布", value: counts.releases },
  ];
  return (
    <section className="page">
      <header className="page-head">
        <h1>概览</h1>
      </header>
      <ul className="kpis">
        {cards.map((card) => (
          <li key={card.label}>
            <strong>{card.value}</strong>
            <span>{card.label}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Snapshots() {
  const { projectId = "" } = useParams();
  const [tick, setTick] = useState(0);
  const snapshots = useLoad(() => api.snapshots(projectId), [projectId, tick]);
  const recipes = useLoad(() => api.recipes(projectId), [projectId, tick]);
  const [datasets, setDatasets] = useState<RagflowDataset[]>([]);
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .ragflowDatasets()
      .then(setDatasets)
      .catch((err) => setError(err.message));
  }, []);

  async function handleSnapshot() {
    const dataset = datasets.find((item) => item.id === picked) ?? datasets[0];
    if (!dataset) {
      setError("RAGFlow 中没有可访问的知识库。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.createSnapshot(projectId, {
        name: dataset.name,
        sources: [{ kb_id: dataset.id }],
      });
      setTick((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRecipe() {
    const snapshot =
      snapshots.status === "ready" ? snapshots.data[0] : undefined;
    const config = {
      task_type: "retrieval",
      seed: { type: "ragflow_snapshot", snapshot_id: snapshot?.id ?? "" },
      models: {},
      columns: [
        {
          name: "query",
          type: "expression",
          params: { expr: "{{ seed.parts | render_parts }}" },
        },
      ],
    };
    await api.createRecipe(projectId, { name: "检索配方", config });
    setTick((n) => n + 1);
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>语料</h1>
      </header>
      {error && <p role="alert">{error}</p>}
      <h2>快照</h2>
      <div className="row">
        <select
          aria-label="知识库"
          value={picked}
          onChange={(event) => setPicked(event.target.value)}
        >
          {datasets.map((dataset) => (
            <option key={dataset.id} value={dataset.id}>
              {dataset.name}（{dataset.doc_num} 文档 / {dataset.chunk_num} 切片
              / {dataset.vector_dim} 维）
            </option>
          ))}
        </select>
        <button className="primary" onClick={handleSnapshot} disabled={busy}>
          {busy ? "构建中…" : "从知识库创建快照"}
        </button>
      </div>
      <View
        state={snapshots}
        onRetry={() => setTick((n) => n + 1)}
        empty={{ title: "还没有快照。" }}
      >
        {(rows) => (
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>状态</th>
                <th>切片</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    {row.name}
                    <br />
                    <code>{row.id}</code>
                  </td>
                  <td>
                    <StatusBadge status={row.status} />
                  </td>
                  <td>{Number(row.stats?.segment_count ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </View>
      <h2>配方</h2>
      <button onClick={handleRecipe}>新建检索配方</button>
      <View
        state={recipes}
        onRetry={() => setTick((n) => n + 1)}
        empty={{ title: "还没有配方。" }}
      >
        {(rows) => (
          <ul className="plain">
            {rows.map((row) => (
              <li key={row.id}>
                {row.name} · {row.task} · v{row.version} ·{" "}
                <StatusBadge status={row.status} />
              </li>
            ))}
          </ul>
        )}
      </View>
    </section>
  );
}

export function Datasets() {
  const { projectId = "" } = useParams();
  const [tick, setTick] = useState(0);
  const state = useLoad(() => api.datasets(projectId), [projectId, tick]);
  return (
    <section className="page">
      <header className="page-head">
        <h1>数据集</h1>
      </header>
      <View
        state={state}
        onRetry={() => setTick((n) => n + 1)}
        empty={{ title: "还没有数据集。运行一个配方来生成。" }}
      >
        {(rows) => (
          <ul className="cards">
            {rows.map((row) => (
              <li key={row.id}>
                <Link to={`/projects/${projectId}/datasets/${row.id}`}>
                  <strong>{row.name}</strong>
                  <span className="muted">{row.sample_count} 条</span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </View>
    </section>
  );
}

export function Samples() {
  const { projectId = "", datasetId = "" } = useParams();
  const [tick, setTick] = useState(0);
  const state = useLoad(
    () => api.samples(projectId, datasetId),
    [datasetId, tick],
  );
  return (
    <section className="page">
      <header className="page-head">
        <h1>样本</h1>
      </header>
      <View
        state={state}
        onRetry={() => setTick((n) => n + 1)}
        empty={{ title: "这个数据集还没有样本。" }}
      >
        {(rows) => (
          <table>
            <thead>
              <tr>
                <th>查询</th>
                <th>划分</th>
                <th>模态</th>
                <th>正例</th>
                <th>负例</th>
                <th>审核</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{row.query || "（空查询）"}</td>
                  <td>{row.split}</td>
                  <td>{row.modality}</td>
                  <td>{row.positives.length}</td>
                  <td>{row.negatives.length}</td>
                  <td>
                    <StatusBadge status={row.review_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </View>
    </section>
  );
}

export function ReviewDesk() {
  const { projectId = "" } = useParams();
  const [tick, setTick] = useState(0);
  const queue = useLoad(() => api.reviewQueue(projectId), [projectId, tick]);
  const [note, setNote] = useState("");

  const current = queue.status === "ready" ? queue.data[0] : null;

  async function handleDecision(decision: "approved" | "rejected") {
    if (!current) return;
    await api.review(projectId, current.id, { decision, reason: "" });
    setNote(
      decision === "approved" ? "已通过，进入下一条。" : "已驳回，进入下一条。",
    );
    setTick((n) => n + 1);
  }

  function handleKey(event: React.KeyboardEvent) {
    if (event.key === "a" || event.key === "A") void handleDecision("approved");
    if (event.key === "r" || event.key === "R") void handleDecision("rejected");
  }

  return (
    <section className="page review" onKeyDown={handleKey} tabIndex={0}>
      <header className="page-head">
        <h1>审核台</h1>
        <span className="muted">A 通过 · R 驳回</span>
      </header>
      {note && <p>{note}</p>}
      <View
        state={queue}
        onRetry={() => setTick((n) => n + 1)}
        empty={{ title: "审核队列已清空。" }}
      >
        {() => (
          <article className="sample-card">
            <p className="query">{current?.query || "（空查询）"}</p>
            <dl>
              <div>
                <dt>划分</dt>
                <dd>{current?.split}</dd>
              </div>
              <div>
                <dt>模态</dt>
                <dd>{current?.modality}</dd>
              </div>
              <div>
                <dt>正例</dt>
                <dd>{current?.positives.length}</dd>
              </div>
              <div>
                <dt>负例</dt>
                <dd>{current?.negatives.length}</dd>
              </div>
            </dl>
            <div className="row">
              <button
                className="primary"
                onClick={() => handleDecision("approved")}
              >
                通过 (A)
              </button>
              <button onClick={() => handleDecision("rejected")}>
                驳回 (R)
              </button>
            </div>
          </article>
        )}
      </View>
    </section>
  );
}

export function Releases() {
  const { projectId = "" } = useParams();
  const [tick, setTick] = useState(0);
  const releases = useLoad(() => api.releases(projectId), [projectId, tick]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [exportText, setExportText] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .datasets(projectId)
      .then(setDatasets)
      .catch(() => setDatasets([]));
  }, [projectId, tick]);

  async function handleRelease() {
    setError("");
    const dataset = datasets[0];
    if (!dataset) {
      setError("没有可发布的数据集。");
      return;
    }
    try {
      await api.release(projectId, dataset.id);
      setTick((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function handleExport(releaseId: string, adapter: string) {
    setError("");
    const result = await api.export(projectId, releaseId, adapter);
    const [name, content] = Object.entries(result.files)[0] ?? ["", ""];
    setExportText(`${name}\n${content.slice(0, 1200)}`);
  }

  return (
    <section className="page">
      <header className="page-head">
        <h1>发布</h1>
        <button className="primary" onClick={handleRelease}>
          发布最新数据集
        </button>
      </header>
      {error && <p role="alert">{error}</p>}
      <View
        state={releases}
        onRetry={() => setTick((n) => n + 1)}
        empty={{
          title: "还没有发布。审核通过样本后即可发布。",
          action: "发布最新数据集",
          onAction: handleRelease,
        }}
      >
        {(rows) => (
          <ul className="plain">
            {rows.map((row) => (
              <li key={row.id}>
                <code>{row.id}</code> · {row.sample_count} 条 ·{" "}
                <StatusBadge status={row.status} />
                <ul>
                  {row.gates.map((gate) => (
                    <li key={gate.name}>
                      {gate.passed ? "通过" : "未通过"} · {gate.name}
                      {gate.detail ? `：${gate.detail}` : ""}
                    </li>
                  ))}
                </ul>
                {row.status === "released" && (
                  <div className="row">
                    {[
                      "canonical",
                      "beir",
                      "sentence_transformers",
                      "flagembedding",
                    ].map((adapter) => (
                      <button
                        key={adapter}
                        onClick={() => handleExport(row.id, adapter)}
                      >
                        {adapter}
                      </button>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </View>
      {exportText && <pre className="export">{exportText}</pre>}
    </section>
  );
}
