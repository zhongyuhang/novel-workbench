import type { CompiledContext, ContextItem } from "../api/types.ts";

const KIND_LABELS: Record<string, string> = {
  system: "系统约束",
  instruction: "本次指令",
  constraints: "本次约束",
  hard_rule: "作品硬规则",
  chapter: "当前章节",
  story_plan: "作品大纲",
  chapter_outline: "章节大纲",
  scene_card: "场景卡片",
  previous_chapter: "上一章",
  next_chapter: "下一章",
  entity: "设定",
  entity_relation: "人物关系",
  event: "事件",
  summary: "章节摘要",
  foreshadowing: "伏笔",
};

type ContextPreviewProps = {
  context: CompiledContext | null;
  pinnedInclude: string[];
  pinnedExclude: string[];
  busy: boolean;
  error: string;
  onPreview: () => void;
  onRecompile: () => void;
  onToggleInclude: (id: string) => void;
  onToggleExclude: (id: string) => void;
};

export function ContextPreview({
  context,
  pinnedInclude,
  pinnedExclude,
  busy,
  error,
  onPreview,
  onRecompile,
  onToggleInclude,
  onToggleExclude,
}: ContextPreviewProps) {
  return (
    <section className="context-panel" aria-label="本次上下文">
      <h3>本次上下文</h3>
      <p className="hint">
        这里只决定接下来这一次生成用哪些材料。固定或排除不会改正式设定，也不会改大纲。
      </p>
      <div className="inline-actions">
        <button className="ghost" type="button" disabled={busy} onClick={onPreview}>
          查看本次上下文
        </button>
        <button className="ghost" type="button" disabled={busy || context === null} onClick={onRecompile}>
          重新编译
        </button>
      </div>
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      {context ? (
        <>
          <p className="hint">
            {context.legacy
              ? "这是较早的任务，当时没有记下逐条来源。"
              : `编译器 ${context.compiler_version || "未知"} · 预算 ${context.budget} 字（估算） · 已纳入约 ${context.total_token_estimate} 字`}
          </p>
          {context.warnings.length > 0 ? (
            <ul aria-label="上下文警告">
              {context.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          ) : null}
          <ul className="context-list">
            {context.items.map((item) => (
              <ContextRow
                key={item.id}
                item={item}
                pinnedInclude={pinnedInclude.includes(item.id)}
                pinnedExclude={pinnedExclude.includes(item.id)}
                busy={busy}
                onToggleInclude={onToggleInclude}
                onToggleExclude={onToggleExclude}
              />
            ))}
          </ul>
          {context.items.length === 0 ? <p className="hint">没有可逐条查看的材料。</p> : null}
        </>
      ) : null}
    </section>
  );
}

function ContextRow({
  item,
  pinnedInclude,
  pinnedExclude,
  busy,
  onToggleInclude,
  onToggleExclude,
}: {
  item: ContextItem;
  pinnedInclude: boolean;
  pinnedExclude: boolean;
  busy: boolean;
  onToggleInclude: (id: string) => void;
  onToggleExclude: (id: string) => void;
}) {
  const label = KIND_LABELS[item.kind] ?? item.kind;
  return (
    <li className={item.included ? "context-item" : "context-item context-excluded"}>
      <header>
        <strong>
          {item.included ? "纳入" : "未纳入"} · {label}
        </strong>
        <span>{item.certainty}</span>
      </header>
      <p>{item.hit_reason}</p>
      <p className="hint">
        来源 {item.source_type}
        {item.source_id ? ` · ${item.source_id}` : ""}
        {item.source_revision !== null ? ` · 修订 ${item.source_revision}` : ""}
        {` · 约 ${item.token_estimate} 字`}
      </p>
      {item.exclusion_reason ? <p>排除原因：{item.exclusion_reason}</p> : null}
      {item.warnings.map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
      <p>{item.content}</p>
      <div className="inline-actions">
        <button
          className="ghost"
          type="button"
          disabled={busy || item.kind === "system"}
          onClick={() => {
            onToggleInclude(item.id);
          }}
        >
          {pinnedInclude ? "取消固定" : "固定纳入"}
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy || item.kind === "system"}
          onClick={() => {
            onToggleExclude(item.id);
          }}
        >
          {pinnedExclude ? "取消排除" : "本次排除"}
        </button>
      </div>
    </li>
  );
}
