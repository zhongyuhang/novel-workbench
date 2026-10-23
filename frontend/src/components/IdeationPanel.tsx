import { useEffect, useState } from "react";
import { ApiError } from "../api/types.ts";
import { listModelConfigs } from "../api/models.ts";
import {
  acceptIdeationCandidate,
  answerIdeation,
  createIdeationSession,
  deferIdeationCandidate,
  generateIdeation,
  listIdeationSessions,
  rejectIdeationCandidate,
  type CandidateKind,
  type IdeationCandidate,
  type IdeationKind,
  type IdeationQuestion,
  type IdeationSession,
} from "../api/ideation.ts";

type IdeationPanelProps = {
  novelId: string;
  onFormalWrite?: () => void;
};

const KIND_LABEL: Record<IdeationKind, string> = {
  guided: "引导式创意",
  world: "世界观",
  character: "人物",
};

const STATUS_LABEL = {
  pending: "待确认",
  accepted: "已确认",
  rejected: "已忽略",
  deferred: "已延后",
} as const;

const FIELD_LABEL: Record<string, string> = {
  direction: "作品方向",
  genre: "题材",
  tone: "调性",
  core_conflict: "核心冲突",
  synopsis: "简介",
  entity_type: "类型",
  name: "名称",
  summary: "说明",
  detail: "细节",
  aliases: "别名",
  role: "身份",
  desire: "想要",
  fear: "害怕",
  note: "备注",
  from_name: "从",
  to_name: "到",
  relation_type: "关系",
  title: "标题",
};

export function IdeationPanel({ novelId, onFormalWrite }: IdeationPanelProps) {
  const [kind, setKind] = useState<IdeationKind>("guided");
  const [sessions, setSessions] = useState<IdeationSession[]>([]);
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  const [modelId, setModelId] = useState("");
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [answer, setAnswer] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([listModelConfigs(controller.signal), listIdeationSessions(novelId, controller.signal)])
      .then(([configs, loaded]) => {
        if (!active) {
          return;
        }
        const real = configs.filter(
          (item) => item.is_enabled && item.provider_type === "openai_compatible",
        );
        setModels(real.map((item) => ({ id: item.id, label: item.display_name })));
        const preferred = real.find((item) => item.is_default) ?? real[0];
        setModelId(preferred?.id ?? "");
        setSessions(loaded);
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "无法读取创意引导。");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [novelId]);

  const session =
    sessions.find(
      (item) => item.kind === kind && !hiddenIds.includes(item.id) && resumable(item),
    ) ?? null;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (cause: unknown) {
      setMessage("");
      setError(cause instanceof ApiError ? cause.message : "这一步没有完成。正式资料和正文没有改。");
    } finally {
      setBusy(false);
    }
  }

  function replaceSession(next: IdeationSession) {
    setSessions((current) => {
      const rest = current.filter((item) => item.id !== next.id);
      return [next, ...rest];
    });
  }

  return (
    <section className="memory-pane" aria-label="创意引导">
      <h2>创意</h2>
      <p className="hint">确认之前不会写入题材、文风、人物、世界观或正文。</p>
      <div className="memory-actions" role="radiogroup" aria-label="设计类型">
        {(Object.keys(KIND_LABEL) as IdeationKind[]).map((value) => (
          <label key={value}>
            <input
              type="radio"
              name="ideation-kind"
              value={value}
              checked={kind === value}
              onChange={() => {
                setKind(value);
                setAnswer("");
                setEditingId(null);
                setMessage("");
              }}
            />
            {KIND_LABEL[value]}
          </label>
        ))}
      </div>
      {session ? (
        <p className="hint">
          这次使用：{session.model_name}
          {session.simulated ? "（模拟，不会访问网络）" : ""}
        </p>
      ) : (
        <div className="stack-form">
          <label>
            这次使用的模型
            <select
              aria-label="这次使用的模型"
              value={modelId}
              onChange={(event) => {
                setModelId(event.target.value);
              }}
            >
              {models.length === 0 ? <option value="">还没有可用模型</option> : null}
              {models.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <div className="memory-actions">
            <button
              className="primary"
              type="button"
              disabled={busy || modelId === ""}
              onClick={() => {
                void run(async () => {
                  const next = await createIdeationSession(novelId, {
                    kind,
                    use_mock: false,
                    model_config_id: modelId,
                  });
                  replaceSession(next);
                  setMessage("模型已固定。先回答问题，生成之后仍是候选。");
                });
              }}
            >
              开始
            </button>
            <button
              className="ghost"
              type="button"
              disabled={busy}
              onClick={() => {
                void run(async () => {
                  const next = await createIdeationSession(novelId, {
                    kind,
                    use_mock: true,
                  });
                  replaceSession(next);
                  setMessage("这是模拟候选，还没有写入正式资料。");
                });
              }}
            >
              先看模拟候选
            </button>
          </div>
        </div>
      )}
      {session?.current_question ? (
        <QuestionForm
          question={session.current_question}
          answer={answer}
          busy={busy}
          onAnswer={setAnswer}
          onSubmit={() => {
            const question = session.current_question;
            if (!question) {
              return;
            }
            const chosen = question.choices.length > 0 ? answer : answer.trim();
            if (!question.optional && chosen === "") {
              setError(question.choices.length > 0 ? "请先选择一项。" : "请先写下回答。");
              return;
            }
            void run(async () => {
              const next = await answerIdeation(session.id, {
                question_id: question.id,
                answer: chosen,
              });
              replaceSession(next);
              setAnswer("");
            });
          }}
        />
      ) : null}
      {session?.ready_to_generate ? (
        <button
          className="primary"
          type="button"
          disabled={busy}
          onClick={() => {
            void run(async () => {
              const result = await generateIdeation(session.id);
              replaceSession(result.session);
              setMessage(result.note);
            });
          }}
        >
          生成候选
        </button>
      ) : null}
      {session && session.candidates.length > 0 ? (
        <ul className="memory-list">
          {session.candidates.map((candidate) => (
            <li key={candidate.id}>
              <CandidateCard
                candidate={candidate}
                editing={editingId === candidate.id}
                draft={draft}
                busy={busy}
                onEdit={() => {
                  setEditingId(candidate.id);
                  setDraft(draftFrom(candidate));
                }}
                onDraft={setDraft}
                onCancelEdit={() => {
                  setEditingId(null);
                }}
                onAccept={(payload) => {
                  void run(async () => {
                    const decision = await acceptIdeationCandidate(candidate.id, payload);
                    replaceCandidate(session.id, decision.candidate);
                    setEditingId(null);
                    if (decision.formal_material_changed) {
                      onFormalWrite?.();
                    }
                    setMessage(
                      decision.formal_material_changed
                        ? "已写入。正文没有改。"
                        : "没有写入正式资料。",
                    );
                  });
                }}
                onReject={() => {
                  void run(async () => {
                    const decision = await rejectIdeationCandidate(candidate.id);
                    replaceCandidate(session.id, decision.candidate);
                    setMessage("已忽略。正式资料和正文没有改。");
                  });
                }}
                onDefer={() => {
                  void run(async () => {
                    const decision = await deferIdeationCandidate(candidate.id);
                    replaceCandidate(session.id, decision.candidate);
                    setMessage("已延后。正式资料和正文没有改。");
                  });
                }}
              />
            </li>
          ))}
        </ul>
      ) : null}
      {session ? (
        <button
          className="ghost"
          type="button"
          onClick={() => {
            setHiddenIds((current) => [...current, session.id]);
            setMessage("");
            setAnswer("");
          }}
        >
          另开一轮
        </button>
      ) : null}
      {message ? <p role="status">{message}</p> : null}
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
    </section>
  );

  function replaceCandidate(sessionId: string, candidate: IdeationCandidate) {
    setSessions((current) =>
      current.map((item) =>
        item.id === sessionId
          ? {
              ...item,
              candidates: item.candidates.map((existing) =>
                existing.id === candidate.id ? candidate : existing,
              ),
            }
          : item,
      ),
    );
  }
}

function QuestionForm({
  question,
  answer,
  busy,
  onAnswer,
  onSubmit,
}: {
  question: IdeationQuestion;
  answer: string;
  busy: boolean;
  onAnswer: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="stack-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <p>{question.prompt}</p>
      <p className="hint">{question.help_text}</p>
      {question.choices.length > 0 ? (
        <div role="radiogroup" aria-label={question.prompt}>
          {question.choices.map((choice) => (
            <label key={choice.id}>
              <input
                type="radio"
                name={question.id}
                value={choice.id}
                checked={answer === choice.id}
                onChange={() => {
                  onAnswer(choice.id);
                }}
              />
              {choice.label}
            </label>
          ))}
        </div>
      ) : (
        <textarea
          aria-label={question.prompt}
          rows={3}
          maxLength={4000}
          value={answer}
          onChange={(event) => {
            onAnswer(event.target.value);
          }}
        />
      )}
      <button className="primary" type="submit" disabled={busy}>
        {question.optional ? "记下这句" : "下一步"}
      </button>
    </form>
  );
}

function CandidateCard({
  candidate,
  editing,
  draft,
  busy,
  onEdit,
  onDraft,
  onCancelEdit,
  onAccept,
  onReject,
  onDefer,
}: {
  candidate: IdeationCandidate;
  editing: boolean;
  draft: Record<string, string>;
  busy: boolean;
  onEdit: () => void;
  onDraft: (value: Record<string, string>) => void;
  onCancelEdit: () => void;
  onAccept: (payload?: Record<string, unknown>) => void;
  onReject: () => void;
  onDefer: () => void;
}) {
  const open = candidate.status === "pending" || candidate.status === "deferred";
  return (
    <article aria-label={candidate.title}>
      <h3>{candidate.title}</h3>
      <p className="hint">
        {kindLabel(candidate.candidate_kind)} · {STATUS_LABEL[candidate.status]}
      </p>
      {candidate.candidate_kind === "work_direction" ? (
        <p className="hint">
          确认调性会写入文风备注。留空则不改已有文风。作品方向写入全书大纲的一句话，状态仍是草稿。
        </p>
      ) : null}
      {editing ? (
        <div className="stack-form">
          {Object.keys(draft).map((key) =>
            key === "entity_type" ? (
              <label key={key}>
                类型
                <select
                  aria-label="类型"
                  value={draft[key] ?? "rule"}
                  onChange={(event) => {
                    onDraft({ ...draft, entity_type: event.target.value });
                  }}
                >
                  <option value="rule">世界规则</option>
                  <option value="location">地点</option>
                  <option value="organization">势力</option>
                </select>
              </label>
            ) : (
              <label key={key}>
                {FIELD_LABEL[key] ?? key}
                <textarea
                  aria-label={FIELD_LABEL[key] ?? key}
                  rows={2}
                  value={draft[key] ?? ""}
                  onChange={(event) => {
                    onDraft({ ...draft, [key]: event.target.value });
                  }}
                />
              </label>
            ),
          )}
          <div className="memory-actions">
            <button
              className="primary"
              type="button"
              disabled={busy}
              onClick={() => {
                onAccept(payloadFrom(candidate.candidate_kind, draft));
              }}
            >
              确认这份修改
            </button>
            <button className="ghost" type="button" onClick={onCancelEdit}>
              取消修改
            </button>
          </div>
        </div>
      ) : (
        <dl>
          {Object.entries(candidate.payload).map(([key, value]) => (
            <div key={key}>
              <dt>{FIELD_LABEL[key] ?? key}</dt>
              <dd>{shown(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {open && !editing ? (
        <div className="memory-actions">
          <button className="primary" type="button" disabled={busy} onClick={() => onAccept()}>
            确认
          </button>
          <button className="ghost" type="button" disabled={busy} onClick={onEdit}>
            修改后确认
          </button>
          <button className="ghost" type="button" disabled={busy} onClick={onReject}>
            忽略
          </button>
          {candidate.status === "pending" ? (
            <button className="ghost" type="button" disabled={busy} onClick={onDefer}>
              延后
            </button>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function resumable(session: IdeationSession): boolean {
  if (session.status === "collecting") {
    return true;
  }
  return session.candidates.some((item) => item.status === "pending" || item.status === "deferred");
}

function kindLabel(kind: CandidateKind): string {
  if (kind === "work_direction") {
    return "作品方向";
  }
  if (kind === "world_setting") {
    return "世界设定";
  }
  if (kind === "character_card") {
    return "人物卡";
  }
  if (kind === "character_relation") {
    return "人物关系";
  }
  return "人物弧线";
}

function shown(value: unknown): string {
  if (typeof value === "string") {
    return value || "（空）";
  }
  if (Array.isArray(value)) {
    return value.filter((item) => typeof item === "string").join("、") || "（空）";
  }
  return "";
}

function draftFrom(candidate: IdeationCandidate): Record<string, string> {
  const draft: Record<string, string> = {};
  for (const [key, value] of Object.entries(candidate.payload)) {
    if (typeof value === "string") {
      draft[key] = value;
    } else if (Array.isArray(value)) {
      draft[key] = value.filter((item) => typeof item === "string").join("、");
    }
  }
  return draft;
}

function payloadFrom(kind: CandidateKind, draft: Record<string, string>): Record<string, unknown> {
  const payload: Record<string, unknown> = { ...draft };
  if (kind === "character_card") {
    payload.aliases = (draft.aliases ?? "")
      .split(/[、,，]/)
      .map((item) => item.trim())
      .filter((item) => item !== "");
    payload.entity_type = "character";
  }
  return payload;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
