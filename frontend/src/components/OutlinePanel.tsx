import { useEffect, useState } from "react";
import { listEntities, type StoryEntity } from "../api/memory.ts";
import {
  PLANNING_STATUS_LABEL,
  confirmChapterOutline,
  confirmStoryPlan,
  createScene,
  deleteScene,
  getChapterOutline,
  getStoryPlan,
  listChapterOutlines,
  listScenes,
  planningFactNote,
  reorderScenes,
  saveChapterOutline,
  saveStoryPlan,
  updateScene,
  type ChapterOutline,
  type EditablePlanningStatus,
  type PlanningStatus,
  type SceneCard,
  type StoryPlan,
} from "../api/planning.ts";
import { ApiError, type ChapterSummary } from "../api/types.ts";

type OutlinePanelProps = {
  novelId: string;
  chapters: ChapterSummary[];
  activeChapterId: string | null;
  onOpenChapter: (chapterId: string) => void;
};

type ChapterPlanEditorProps = {
  novelId: string;
  chapterId: string;
  chapterTitle: string;
};

type OutlineDraft = {
  goal: string;
  mustAdvance: string;
  requiredEvents: string;
  allowedReveals: string;
  forbiddenReveals: string;
  targetWords: string;
  endingHook: string;
  status: EditablePlanningStatus;
};

type SceneDraft = {
  goal: string;
  locationId: string;
  characterIds: string[];
  conflict: string;
  turningPoint: string;
  expectedOutcome: string;
  mustConvey: string;
  mustNotReveal: string;
  status: PlanningStatus;
};

const EDITABLE_STATUSES: Array<{ value: EditablePlanningStatus; label: string }> = [
  { value: "draft", label: "草稿" },
  { value: "stale", label: "待复核" },
  { value: "archived", label: "已归档" },
];

const SCENE_STATUSES: Array<{ value: PlanningStatus; label: string }> = [
  { value: "draft", label: "草稿" },
  { value: "confirmed", label: "已确认" },
  { value: "stale", label: "待复核" },
  { value: "archived", label: "已归档" },
];

export function OutlinePanel({
  novelId,
  chapters,
  activeChapterId,
  onOpenChapter,
}: OutlinePanelProps) {
  const [plan, setPlan] = useState<StoryPlan | null>(null);
  const [outlines, setOutlines] = useState<ChapterOutline[]>([]);
  const [logline, setLogline] = useState("");
  const [body, setBody] = useState("");
  const [ending, setEnding] = useState("");
  const [status, setStatus] = useState<EditablePlanningStatus>("draft");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([getStoryPlan(novelId, controller.signal), listChapterOutlines(novelId, controller.signal)])
      .then(([story, rows]) => {
        if (!active) {
          return;
        }
        setPlan(story.plan);
        applyPlan(story.plan, setLogline, setBody, setEnding, setStatus);
        setOutlines(rows);
        setError("");
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(messageFrom(cause, "无法读取大纲。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [novelId]);

  const outlineByChapter = new Map(outlines.map((item) => [item.chapter_id, item]));

  async function savePlan() {
    setBusy(true);
    setError("");
    try {
      const saved = await saveStoryPlan(novelId, {
        logline: blank(logline),
        body: blank(body),
        ending_intent: blank(ending),
        status,
        expected_revision: plan?.revision,
      });
      setPlan(saved);
      applyPlan(saved, setLogline, setBody, setEnding, setStatus);
      setMessage("作品大纲已保存。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "作品大纲没有保存。"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmPlan() {
    if (!plan) {
      setError("先保存作品大纲，再确认。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const saved = await confirmStoryPlan(novelId, plan.revision);
      setPlan(saved);
      applyPlan(saved, setLogline, setBody, setEnding, setStatus);
      setMessage("作品大纲已确认。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "作品大纲没有确认。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="plan-pane">
      <h2>大纲</h2>
      <p className="hint">目录仍在旁边。没有大纲的章节可以继续写正文。</p>
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      {message ? <p role="status">{message}</p> : null}
      <form
        className="plan-form"
        onSubmit={(event) => {
          event.preventDefault();
          void savePlan();
        }}
      >
        <h3>作品大纲</h3>
        <StatusBadge status={plan?.status ?? null} countsAsFact={plan?.counts_as_fact ?? false} />
        <label>
          一句话
          <input
            aria-label="作品大纲一句话"
            value={logline}
            maxLength={500}
            onChange={(event) => {
              setLogline(event.target.value);
            }}
          />
        </label>
        <label>
          全书大纲
          <textarea
            aria-label="全书大纲"
            value={body}
            maxLength={20000}
            onChange={(event) => {
              setBody(event.target.value);
            }}
          />
        </label>
        <label>
          结局意向
          <textarea
            aria-label="结局意向"
            value={ending}
            maxLength={2000}
            onChange={(event) => {
              setEnding(event.target.value);
            }}
          />
        </label>
        <label>
          保存后的状态
          <select
            aria-label="作品大纲状态"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as EditablePlanningStatus);
            }}
          >
            {EDITABLE_STATUSES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <div className="inline-actions">
          <button className="primary" type="submit" disabled={busy}>
            保存作品大纲
          </button>
          <button
            className="ghost"
            type="button"
            disabled={busy || plan === null || plan.status === "confirmed"}
            onClick={() => {
              void confirmPlan();
            }}
          >
            确认作品大纲
          </button>
        </div>
      </form>
      <h3>章节</h3>
      {chapters.length === 0 ? <p className="hint">还没有章节。先在目录里新建，再写章节大纲。</p> : null}
      <ol className="toc-list">
        {chapters.map((chapter) => {
          const outline = outlineByChapter.get(chapter.id) ?? null;
          return (
            <li key={chapter.id} className={chapter.id === activeChapterId ? "toc-current" : undefined}>
              <button
                className="toc-link"
                type="button"
                onClick={() => {
                  onOpenChapter(chapter.id);
                }}
              >
                <span>{chapter.title}</span>
                <span className="hint">{outline ? PLANNING_STATUS_LABEL[outline.status] : "无大纲"}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function ChapterPlanEditor({ novelId, chapterId, chapterTitle }: ChapterPlanEditorProps) {
  const [outline, setOutline] = useState<ChapterOutline | null>(null);
  const [draft, setDraft] = useState<OutlineDraft>(emptyOutline());
  const [scenes, setScenes] = useState<SceneCard[]>([]);
  const [sceneDrafts, setSceneDrafts] = useState<Record<string, SceneDraft>>({});
  const [entities, setEntities] = useState<StoryEntity[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getChapterOutline(chapterId, controller.signal),
      listScenes(chapterId, controller.signal),
      listEntities(novelId, controller.signal),
    ])
      .then(([nextOutline, nextScenes, nextEntities]) => {
        if (!active) {
          return;
        }
        setOutline(nextOutline.outline);
        setDraft(outlineDraft(nextOutline.outline));
        applyScenes(nextScenes, setScenes, setSceneDrafts);
        setEntities(nextEntities);
        setError("");
        setReady(true);
      })
      .catch((cause: unknown) => {
        if (!active || isAbort(cause)) {
          return;
        }
        setError(messageFrom(cause, "无法读取章节大纲。"));
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [chapterId, novelId]);

  const locations = entities.filter((item) => item.entity_type === "location");
  const characters = entities.filter((item) => item.entity_type === "character");

  async function createOutline() {
    setBusy(true);
    setError("");
    try {
      const saved = await saveChapterOutline(chapterId, { status: "draft" });
      setOutline(saved);
      setDraft(outlineDraft(saved));
      setMessage("已建立章节大纲草稿。没有大纲时仍可写正文。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "章节大纲没有建立。"));
    } finally {
      setBusy(false);
    }
  }

  async function saveOutline() {
    if (!outline) {
      return;
    }
    const targetWords = draft.targetWords.trim();
    let parsedWords: number | null = null;
    if (targetWords !== "") {
      parsedWords = Number(targetWords);
      if (!Number.isInteger(parsedWords) || parsedWords < 1) {
        setError("目标字数需要是大于 0 的整数，或留空。");
        return;
      }
    }
    setBusy(true);
    setError("");
    try {
      const saved = await saveChapterOutline(chapterId, {
        goal: blank(draft.goal),
        must_advance: blank(draft.mustAdvance),
        required_events: blank(draft.requiredEvents),
        allowed_reveals: blank(draft.allowedReveals),
        forbidden_reveals: blank(draft.forbiddenReveals),
        target_words: parsedWords,
        ending_hook: blank(draft.endingHook),
        status: draft.status,
        expected_revision: outline.revision,
      });
      setOutline(saved);
      setDraft(outlineDraft(saved));
      setMessage("章节大纲已保存。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "章节大纲没有保存。"));
    } finally {
      setBusy(false);
    }
  }

  async function confirmOutline() {
    if (!outline) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      const saved = await confirmChapterOutline(chapterId, outline.revision);
      setOutline(saved);
      setDraft(outlineDraft(saved));
      setMessage("章节大纲已确认。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "章节大纲没有确认。"));
    } finally {
      setBusy(false);
    }
  }

  async function addScene() {
    setBusy(true);
    setError("");
    try {
      await createScene(chapterId, { goal: "新场景", status: "draft" });
      applyScenes(await listScenes(chapterId), setScenes, setSceneDrafts);
      setMessage("已添加场景卡片。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "场景卡片没有添加。"));
    } finally {
      setBusy(false);
    }
  }

  async function saveScene(scene: SceneCard) {
    const current = sceneDrafts[scene.id];
    if (!current) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await updateScene(scene.id, {
        goal: blank(current.goal),
        location_entity_id: current.locationId || null,
        character_entity_ids: current.characterIds,
        conflict: blank(current.conflict),
        turning_point: blank(current.turningPoint),
        expected_outcome: blank(current.expectedOutcome),
        must_convey: blank(current.mustConvey),
        must_not_reveal: blank(current.mustNotReveal),
        status: current.status,
        expected_revision: scene.revision,
      });
      applyScenes(await listScenes(chapterId), setScenes, setSceneDrafts);
      setMessage("场景卡片已保存。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "场景卡片没有保存。"));
    } finally {
      setBusy(false);
    }
  }

  async function removeScene(scene: SceneCard) {
    if (!window.confirm(`删除场景「${scene.goal ?? "未命名"}」？`)) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await deleteScene(scene.id);
      applyScenes(await listScenes(chapterId), setScenes, setSceneDrafts);
      setMessage("场景卡片已删除。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "场景卡片没有删除。"));
    } finally {
      setBusy(false);
    }
  }

  async function moveScene(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= scenes.length) {
      return;
    }
    const ids = scenes.map((scene) => scene.id);
    const current = ids[index];
    const next = ids[target];
    if (!current || !next) {
      return;
    }
    ids[index] = next;
    ids[target] = current;
    setBusy(true);
    setError("");
    try {
      const rows = await reorderScenes(chapterId, ids);
      applyScenes(rows, setScenes, setSceneDrafts);
      setMessage("场景顺序已保存。");
    } catch (cause: unknown) {
      setError(messageFrom(cause, "场景顺序没有保存。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="plan-pane" aria-label="章节大纲">
      <h2>章节大纲</h2>
      <p className="hint">
        {chapterTitle}。没有大纲也可以写正文、保存和导出。地点和人物只引用设定里的实体，不复制档案。
      </p>
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      {message ? <p role="status">{message}</p> : null}
      {!ready ? <p role="status">正在读取章节大纲</p> : null}
      {ready && outline === null ? (
        <div className="empty">
          <p>这一章还没有章节大纲。未确认的大纲不会当作强制事实。</p>
          <button className="primary" type="button" disabled={busy} onClick={() => void createOutline()}>
            写下章节大纲
          </button>
        </div>
      ) : null}
      {outline ? (
        <form
          className="plan-form"
          onSubmit={(event) => {
            event.preventDefault();
            void saveOutline();
          }}
        >
          <StatusBadge status={outline.status} countsAsFact={outline.counts_as_fact} />
          <label>
            一句话目标
            <input
              aria-label="章节目标"
              value={draft.goal}
              maxLength={500}
              onChange={(event) => {
                setDraft({ ...draft, goal: event.target.value });
              }}
            />
          </label>
          <label>
            必须推进
            <textarea
              aria-label="必须推进"
              value={draft.mustAdvance}
              maxLength={4000}
              onChange={(event) => {
                setDraft({ ...draft, mustAdvance: event.target.value });
              }}
            />
          </label>
          <label>
            必须出现
            <textarea
              aria-label="必须出现"
              value={draft.requiredEvents}
              maxLength={4000}
              onChange={(event) => {
                setDraft({ ...draft, requiredEvents: event.target.value });
              }}
            />
          </label>
          <label>
            允许揭露
            <textarea
              aria-label="允许揭露"
              value={draft.allowedReveals}
              maxLength={4000}
              onChange={(event) => {
                setDraft({ ...draft, allowedReveals: event.target.value });
              }}
            />
          </label>
          <label>
            禁止揭露
            <textarea
              aria-label="禁止揭露"
              value={draft.forbiddenReveals}
              maxLength={4000}
              onChange={(event) => {
                setDraft({ ...draft, forbiddenReveals: event.target.value });
              }}
            />
          </label>
          <label>
            目标字数
            <input
              aria-label="章节目标字数"
              inputMode="numeric"
              value={draft.targetWords}
              onChange={(event) => {
                setDraft({ ...draft, targetWords: event.target.value });
              }}
            />
          </label>
          <label>
            结尾钩子
            <input
              aria-label="结尾钩子"
              value={draft.endingHook}
              maxLength={1000}
              onChange={(event) => {
                setDraft({ ...draft, endingHook: event.target.value });
              }}
            />
          </label>
          <label>
            保存后的状态
            <select
              aria-label="章节大纲状态"
              value={draft.status}
              onChange={(event) => {
                setDraft({ ...draft, status: event.target.value as EditablePlanningStatus });
              }}
            >
              {EDITABLE_STATUSES.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <p className="hint">保存修改不会把草稿标成已确认。确认按钮才会。</p>
          <div className="inline-actions">
            <button className="primary" type="submit" disabled={busy}>
              保存章节大纲
            </button>
            <button
              className="ghost"
              type="button"
              disabled={busy || outline.status === "confirmed"}
              onClick={() => {
                void confirmOutline();
              }}
            >
              确认章节大纲
            </button>
          </div>
        </form>
      ) : null}
      <div className="pane-toolbar">
        <h3>场景卡片</h3>
        <button className="ghost" type="button" disabled={busy || !ready} onClick={() => void addScene()}>
          添加场景卡片
        </button>
      </div>
      {scenes.length === 0 && ready ? <p className="hint">还没有场景。可以先写正文。</p> : null}
      {scenes.map((scene, index) => {
        const current = sceneDrafts[scene.id];
        if (!current) {
          return null;
        }
        return (
          <form
            key={scene.id}
            className="scene-card"
            aria-label={`场景 ${index + 1}`}
            onSubmit={(event) => {
              event.preventDefault();
              void saveScene(scene);
            }}
          >
            <StatusBadge status={scene.status} countsAsFact={scene.counts_as_fact} />
            <label>
              场景目标
              <input
                aria-label={`场景目标 ${scene.id}`}
                value={current.goal}
                maxLength={500}
                onChange={(event) => {
                  updateSceneDraft(setSceneDrafts, scene.id, { goal: event.target.value });
                }}
              />
            </label>
            <label>
              地点
              <select
                aria-label={`场景地点 ${scene.id}`}
                value={current.locationId}
                onChange={(event) => {
                  updateSceneDraft(setSceneDrafts, scene.id, { locationId: event.target.value });
                }}
              >
                <option value="">不指定地点</option>
                {locations.map((place) => (
                  <option key={place.id} value={place.id}>
                    {place.name}
                  </option>
                ))}
              </select>
            </label>
            {scene.location && !scene.location.available ? <p className="hint">地点引用已失效。</p> : null}
            <fieldset>
              <legend>出场人物</legend>
              {characters.length === 0 ? <p className="hint">设定里还没有人物。</p> : null}
              {characters.map((person) => (
                <label key={person.id} className="check-row">
                  <input
                    type="checkbox"
                    checked={current.characterIds.includes(person.id)}
                    onChange={() => {
                      const has = current.characterIds.includes(person.id);
                      updateSceneDraft(setSceneDrafts, scene.id, {
                        characterIds: has
                          ? current.characterIds.filter((id) => id !== person.id)
                          : [...current.characterIds, person.id],
                      });
                    }}
                  />
                  {person.name}
                </label>
              ))}
            </fieldset>
            {scene.characters.some((person) => !person.available) ? (
              <p className="hint">有人物引用已失效。</p>
            ) : null}
            <label>
              冲突
              <textarea
                aria-label={`场景冲突 ${scene.id}`}
                value={current.conflict}
                maxLength={2000}
                onChange={(event) => {
                  updateSceneDraft(setSceneDrafts, scene.id, { conflict: event.target.value });
                }}
              />
            </label>
            <label>
              转折
              <textarea
                aria-label={`场景转折 ${scene.id}`}
                value={current.turningPoint}
                maxLength={2000}
                onChange={(event) => {
                  updateSceneDraft(setSceneDrafts, scene.id, { turningPoint: event.target.value });
                }}
              />
            </label>
            <label>
              预期结果
              <textarea
                aria-label={`场景预期结果 ${scene.id}`}
                value={current.expectedOutcome}
                maxLength={2000}
                onChange={(event) => {
                  updateSceneDraft(setSceneDrafts, scene.id, { expectedOutcome: event.target.value });
                }}
              />
            </label>
            <label>
              必须传达
              <textarea
                aria-label={`必须传达 ${scene.id}`}
                value={current.mustConvey}
                maxLength={2000}
                onChange={(event) => {
                  updateSceneDraft(setSceneDrafts, scene.id, { mustConvey: event.target.value });
                }}
              />
            </label>
            <label>
              不得透露
              <textarea
                aria-label={`不得透露 ${scene.id}`}
                value={current.mustNotReveal}
                maxLength={2000}
                onChange={(event) => {
                  updateSceneDraft(setSceneDrafts, scene.id, { mustNotReveal: event.target.value });
                }}
              />
            </label>
            <label>
              场景状态
              <select
                aria-label={`场景状态 ${scene.id}`}
                value={current.status}
                onChange={(event) => {
                  updateSceneDraft(setSceneDrafts, scene.id, {
                    status: event.target.value as PlanningStatus,
                  });
                }}
              >
                {SCENE_STATUSES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="inline-actions">
              <button className="primary" type="submit" disabled={busy}>
                保存场景
              </button>
              <button
                className="ghost"
                type="button"
                disabled={busy || index === 0}
                onClick={() => {
                  void moveScene(index, -1);
                }}
              >
                上移场景
              </button>
              <button
                className="ghost"
                type="button"
                disabled={busy || index === scenes.length - 1}
                onClick={() => {
                  void moveScene(index, 1);
                }}
              >
                下移场景
              </button>
              <button
                className="ghost danger"
                type="button"
                disabled={busy}
                onClick={() => {
                  void removeScene(scene);
                }}
              >
                删除场景
              </button>
            </div>
          </form>
        );
      })}
    </section>
  );
}

function StatusBadge({
  status,
  countsAsFact,
}: {
  status: PlanningStatus | null;
  countsAsFact: boolean;
}) {
  const label = status ? PLANNING_STATUS_LABEL[status] : "无大纲";
  return (
    <p className={countsAsFact ? "plan-status plan-status-confirmed" : "plan-status"}>
      <span>{label}</span>
      <span> {planningFactNote(countsAsFact)}</span>
    </p>
  );
}

function applyPlan(
  plan: StoryPlan | null,
  setLogline: (value: string) => void,
  setBody: (value: string) => void,
  setEnding: (value: string) => void,
  setStatus: (value: EditablePlanningStatus) => void,
) {
  setLogline(plan?.logline ?? "");
  setBody(plan?.body ?? "");
  setEnding(plan?.ending_intent ?? "");
  setStatus(editableStatus(plan?.status ?? "draft"));
}

function applyScenes(
  rows: SceneCard[],
  setScenes: (rows: SceneCard[]) => void,
  setDrafts: (drafts: Record<string, SceneDraft>) => void,
) {
  setScenes(rows);
  setDrafts(Object.fromEntries(rows.map((row) => [row.id, sceneDraft(row)])));
}

function updateSceneDraft(
  setDrafts: (value: (current: Record<string, SceneDraft>) => Record<string, SceneDraft>) => void,
  sceneId: string,
  patch: Partial<SceneDraft>,
) {
  setDrafts((current) => {
    const existing = current[sceneId];
    if (!existing) {
      return current;
    }
    return { ...current, [sceneId]: { ...existing, ...patch } };
  });
}

function emptyOutline(): OutlineDraft {
  return {
    goal: "",
    mustAdvance: "",
    requiredEvents: "",
    allowedReveals: "",
    forbiddenReveals: "",
    targetWords: "",
    endingHook: "",
    status: "draft",
  };
}

function outlineDraft(outline: ChapterOutline | null): OutlineDraft {
  if (!outline) {
    return emptyOutline();
  }
  return {
    goal: outline.goal ?? "",
    mustAdvance: outline.must_advance ?? "",
    requiredEvents: outline.required_events ?? "",
    allowedReveals: outline.allowed_reveals ?? "",
    forbiddenReveals: outline.forbidden_reveals ?? "",
    targetWords: outline.target_words === null ? "" : String(outline.target_words),
    endingHook: outline.ending_hook ?? "",
    status: editableStatus(outline.status),
  };
}

function sceneDraft(scene: SceneCard): SceneDraft {
  return {
    goal: scene.goal ?? "",
    locationId: scene.location_entity_id ?? "",
    characterIds: scene.character_entity_ids,
    conflict: scene.conflict ?? "",
    turningPoint: scene.turning_point ?? "",
    expectedOutcome: scene.expected_outcome ?? "",
    mustConvey: scene.must_convey ?? "",
    mustNotReveal: scene.must_not_reveal ?? "",
    status: scene.status,
  };
}

function editableStatus(status: PlanningStatus): EditablePlanningStatus {
  if (status === "stale" || status === "archived") {
    return status;
  }
  return "draft";
}

function blank(value: string): string | null {
  const cleaned = value.trim();
  return cleaned === "" ? null : cleaned;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
