import { useEffect, useState } from "react";
import { ApiError } from "../api/types.ts";
import { listModelConfigs } from "../api/models.ts";
import { listEntities, type StoryEntity, type StoryEventRecord } from "../api/memory.ts";
import { listStoryArcs, type StoryArc } from "../api/planning.ts";
import { listForeshadowing, type Foreshadowing } from "../api/quality.ts";
import {
  acceptChronicleCandidate,
  createChronicleEvent,
  deferChronicleCandidate,
  deleteChronicleEvent,
  getChronicle,
  listChronicleCandidates,
  planChronicle,
  rejectChronicleCandidate,
  type ChronicleCandidate,
  type ChronicleEventWrite,
} from "../api/chronicle.ts";

type ChapterOption = {
  id: string;
  title: string;
};

type ChroniclePanelProps = {
  novelId: string;
  chapters: ChapterOption[];
  onFormalWrite?: () => void;
};

const CERTAINTY_LABEL = {
  confirmed: "已确认",
  inferred: "推断",
  uncertain: "不确定",
} as const;

const STATUS_LABEL = {
  pending: "待确认",
  accepted: "已写入",
  rejected: "已忽略",
  deferred: "已延后",
} as const;

export function ChroniclePanel({ novelId, chapters, onFormalWrite }: ChroniclePanelProps) {
  const [events, setEvents] = useState<StoryEventRecord[]>([]);
  const [candidates, setCandidates] = useState<ChronicleCandidate[]>([]);
  const [entities, setEntities] = useState<StoryEntity[]>([]);
  const [arcs, setArcs] = useState<StoryArc[]>([]);
  const [hooks, setHooks] = useState<Foreshadowing[]>([]);
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [modelId, setModelId] = useState("");
  const [hint, setHint] = useState("");
  const [title, setTitle] = useState("");
  const [when, setWhen] = useState("");
  const [description, setDescription] = useState("");
  const [names, setNames] = useState("");
  const [characterIds, setCharacterIds] = useState<string[]>([]);
  const [chapterId, setChapterId] = useState("");
  const [arcId, setArcId] = useState("");
  const [hookId, setHookId] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getChronicle(novelId, controller.signal),
      listChronicleCandidates(novelId, controller.signal),
      listEntities(novelId, controller.signal),
      listStoryArcs(novelId, controller.signal),
      listForeshadowing(novelId, undefined, controller.signal),
      listModelConfigs(controller.signal),
    ])
      .then(([chronicle, planned, people, threads, foreshadows, configs]) => {
        if (!active) {
          return;
        }
        setEvents(chronicle.events);
        setCandidates(planned);
        setEntities(people);
        setArcs(threads);
        setHooks(foreshadows);
        const real = configs.filter(
          (item) => item.is_enabled && item.provider_type === "openai_compatible",
        );
        setModels(real.map((item) => ({ id: item.id, label: item.display_name })));
        const preferred = real.find((item) => item.is_default) ?? real[0];
        setModelId(preferred?.id ?? "");
        setError("");
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "无法读取编年史。");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [novelId]);

  const characters = entities.filter((item) => item.entity_type === "character");

  async function reload() {
    const [chronicle, planned] = await Promise.all([
      getChronicle(novelId),
      listChronicleCandidates(novelId),
    ]);
    setEvents(chronicle.events);
    setCandidates(planned);
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "编年史没有保存。");
    } finally {
      setBusy(false);
    }
  }

  function draftFromForm(): ChronicleEventWrite {
    return {
      title: title.trim() || null,
      description: description.trim(),
      event_time_text: when.trim() || null,
      participants: splitNames(names),
      participant_entity_ids: characterIds,
      chapter_id: chapterId || null,
      story_arc_id: arcId || null,
      foreshadowing_id: hookId || null,
      certainty: "confirmed",
    };
  }

  return (
    <section className="chronicle-pane" aria-label="编年史">
      <h2>编年史</h2>
      <p className="hint">
        按发生时间排列。能读出的公历、「第N天」和「第N章」各自成组，读不出时间的排在后面。AI
        规划要确认后才写入正式事件。
      </p>
      {error ? <p className="error">{error}</p> : null}
      {message ? <p className="hint">{message}</p> : null}
      {events.length === 0 ? <p className="hint">还没有编年史事件。</p> : null}
      <ol className="chronicle-list" aria-label="编年史">
        {events.map((event) => (
          <li key={event.id}>
            <article className="memory-card">
              <p>
                <strong>{event.event_time_text || "时间未填写"}</strong>
                {event.title ? ` · ${event.title}` : ""}
              </p>
              <p>{event.description}</p>
              <p className="hint">
                {CERTAINTY_LABEL[event.certainty]}
                {event.chapter_id ? ` · ${event.chapter_title}` : " · 尚未关联章节"}
                {event.participants.length > 0 ? ` · ${event.participants.join("、")}` : ""}
                {linkedNames(event, characters)}
                {arcTitle(event, arcs)}
                {hookTitle(event, hooks)}
              </p>
              <button
                className="ghost"
                type="button"
                disabled={busy}
                onClick={() => {
                  void run(async () => {
                    await deleteChronicleEvent(event.id);
                    await reload();
                    onFormalWrite?.();
                    setMessage("已从编年史移出。正文没有改。");
                  });
                }}
              >
                移出
              </button>
            </article>
          </li>
        ))}
      </ol>

      <h3>手动记录</h3>
      <form
        className="memory-form"
        onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await createChronicleEvent(novelId, draftFromForm());
            setTitle("");
            setWhen("");
            setDescription("");
            setNames("");
            setCharacterIds([]);
            setChapterId("");
            setArcId("");
            setHookId("");
            await reload();
            onFormalWrite?.();
            setMessage("已写入编年史。正文没有改。");
          });
        }}
      >
        <label>
          标题
          <input
            aria-label="事件标题"
            value={title}
            onChange={(event) => {
              setTitle(event.target.value);
            }}
          />
        </label>
        <label>
          发生时间
          <input
            aria-label="发生时间"
            value={when}
            placeholder="如 第3天、2020-01-02、第2章"
            onChange={(event) => {
              setWhen(event.target.value);
            }}
          />
        </label>
        <label>
          事件
          <textarea
            aria-label="事件描述"
            value={description}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
          />
        </label>
        <label>
          参与者
          <input
            aria-label="参与者"
            value={names}
            placeholder="用顿号或逗号分开。与人物同名会自动关联"
            onChange={(event) => {
              setNames(event.target.value);
            }}
          />
        </label>
        <label>
          人物
          <select
            aria-label="关联人物"
            multiple
            value={characterIds}
            onChange={(event) => {
              setCharacterIds(
                Array.from(event.target.selectedOptions, (option) => option.value),
              );
            }}
          >
            {characters.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          章节
          <select
            aria-label="关联章节"
            value={chapterId}
            onChange={(event) => {
              setChapterId(event.target.value);
            }}
          >
            <option value="">不关联章节</option>
            {chapters.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          故事线
          <select
            aria-label="关联故事线"
            value={arcId}
            onChange={(event) => {
              setArcId(event.target.value);
            }}
          >
            <option value="">不关联故事线</option>
            {arcs.map((item) => (
              <option key={item.id} value={item.id}>
                {item.title}
              </option>
            ))}
          </select>
        </label>
        <label>
          伏笔
          <select
            aria-label="关联伏笔"
            value={hookId}
            onChange={(event) => {
              setHookId(event.target.value);
            }}
          >
            <option value="">不关联伏笔</option>
            {hooks.map((item) => (
              <option key={item.id} value={item.id}>
                {item.description}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" type="submit" disabled={busy || description.trim() === ""}>
          记入编年史
        </button>
      </form>

      <h3>事件规划</h3>
      <label>
        想补上什么
        <textarea
          aria-label="规划说明"
          value={hint}
          onChange={(event) => {
            setHint(event.target.value);
          }}
        />
      </label>
      <label>
        本次模型
        <select
          aria-label="规划使用的模型"
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
          className="ghost"
          type="button"
          disabled={busy}
          onClick={() => {
            void run(async () => {
              const planned = await planChronicle(novelId, {
                hint: hint.trim() || null,
                use_mock: true,
              });
              setCandidates((current) => [...planned.candidates, ...current]);
              setMessage(planned.note);
            });
          }}
        >
          生成模拟候选
        </button>
        <button
          className="primary"
          type="button"
          disabled={busy || modelId === ""}
          onClick={() => {
            void run(async () => {
              const planned = await planChronicle(novelId, {
                hint: hint.trim() || null,
                use_mock: false,
                model_config_id: modelId,
              });
              setCandidates((current) => [...planned.candidates, ...current]);
              setMessage(planned.note);
            });
          }}
        >
          用所选模型生成
        </button>
      </div>
      <ul className="memory-list" aria-label="事件候选">
        {candidates
          .filter((item) => item.status === "pending" || item.status === "deferred")
          .map((candidate) => (
            <CandidateCard
              key={candidate.id}
              candidate={candidate}
              busy={busy}
              onReview={(action, event) => {
                void run(async () => {
                  if (action === "accept") {
                    await acceptChronicleCandidate(candidate.id, event);
                    await reload();
                    onFormalWrite?.();
                    setMessage("已确认并写入编年史。");
                    return;
                  }
                  if (action === "reject") {
                    await rejectChronicleCandidate(candidate.id);
                  } else {
                    await deferChronicleCandidate(candidate.id);
                  }
                  await reload();
                  setMessage(action === "reject" ? "已忽略，没有写入正式事件。" : "已延后。");
                });
              }}
            />
          ))}
      </ul>
    </section>
  );
}

function CandidateCard({
  candidate,
  busy,
  onReview,
}: {
  candidate: ChronicleCandidate;
  busy: boolean;
  onReview: (action: "accept" | "reject" | "defer", event?: ChronicleEventWrite) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [description, setDescription] = useState(candidate.description);
  const [when, setWhen] = useState(candidate.event_time_text ?? "");

  return (
    <li className="memory-card">
      <p>
        <strong>{candidate.event_time_text || "时间未填写"}</strong>
        {candidate.title ? ` · ${candidate.title}` : ""}
        {` · ${STATUS_LABEL[candidate.status]}`}
      </p>
      <p>{candidate.description}</p>
      {editing ? (
        <>
          <label>
            修改描述
            <textarea
              aria-label="修改候选描述"
              value={description}
              onChange={(event) => {
                setDescription(event.target.value);
              }}
            />
          </label>
          <label>
            修改时间
            <input
              aria-label="修改候选时间"
              value={when}
              onChange={(event) => {
                setWhen(event.target.value);
              }}
            />
          </label>
        </>
      ) : null}
      <div className="memory-actions">
        <button
          className="primary"
          type="button"
          disabled={busy || (editing && description.trim() === "")}
          onClick={() => {
            onReview(
              "accept",
              editing
                ? {
                    title: candidate.title,
                    description: description.trim(),
                    event_time_text: when.trim() || null,
                    participants: candidate.participants,
                    participant_entity_ids: candidate.participant_entity_ids,
                    certainty: "inferred",
                  }
                : undefined,
            );
          }}
        >
          确认
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy}
          onClick={() => {
            setEditing((value) => !value);
          }}
        >
          修改后确认
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy}
          onClick={() => {
            onReview("reject");
          }}
        >
          忽略
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy || candidate.status !== "pending"}
          onClick={() => {
            onReview("defer");
          }}
        >
          延后
        </button>
      </div>
    </li>
  );
}

function linkedNames(event: StoryEventRecord, characters: StoryEntity[]): string {
  const names = characters
    .filter((item) => event.participant_entity_ids.includes(item.id))
    .map((item) => item.name);
  return names.length > 0 ? ` · 人物 ${names.join("、")}` : "";
}

function arcTitle(event: StoryEventRecord, arcs: StoryArc[]): string {
  const arc = arcs.find((item) => item.id === event.story_arc_id);
  return arc ? ` · 故事线 ${arc.title}` : "";
}

function hookTitle(event: StoryEventRecord, hooks: Foreshadowing[]): string {
  const hook = hooks.find((item) => item.id === event.foreshadowing_id);
  return hook ? ` · 伏笔 ${hook.description}` : "";
}

function splitNames(value: string): string[] {
  return value
    .split(/[、，,；;\n]+/)
    .map((item) => item.trim())
    .filter((item) => item !== "");
}

function isAbort(cause: unknown): boolean {
  return cause instanceof DOMException && cause.name === "AbortError";
}
