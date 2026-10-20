import { useEffect, useState } from "react";
import { listModelConfigs } from "../api/models.ts";
import { listEntities, type StoryEntity } from "../api/memory.ts";
import {
  PLANNING_STATUS_LABEL,
  STORY_ARC_TYPE_LABEL,
  acceptOutlineCandidate,
  confirmChapterOutline,
  confirmStoryArc,
  confirmStoryPlan,
  confirmVolumeOutline,
  createScene,
  createStoryArc,
  deleteScene,
  deleteStoryArc,
  getChapterOutline,
  getStoryPlan,
  listChapterOutlines,
  listScenes,
  listStoryArcs,
  listVolumeOutlines,
  planningFactNote,
  previewOutlineCandidate,
  reorderScenes,
  reorderStoryArcs,
  saveChapterOutline,
  saveStoryPlan,
  saveVolumeOutline,
  updateScene,
  updateStoryArc,
  type ChapterOutline,
  type EditablePlanningStatus,
  type OutlineCandidatePreview,
  type PlanningStatus,
  type SceneCard,
  type StoryArc,
  type StoryArcType,
  type StoryPlan,
  type VolumeOutline,
} from "../api/planning.ts";
import { ApiError, type ChapterSummary, type ModelConfig, type Volume } from "../api/types.ts";

type OutlinePanelProps = {
  novelId: string;
  chapters: ChapterSummary[];
  volumes: Volume[];
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
  volumes,
  activeChapterId,
  onOpenChapter,
}: OutlinePanelProps) {
  const [plan, setPlan] = useState<StoryPlan | null>(null);
  const [arcs, setArcs] = useState<StoryArc[]>([]);
  const [volumeOutlines, setVolumeOutlines] = useState<VolumeOutline[]>([]);
  const [outlines, setOutlines] = useState<ChapterOutline[]>([]);
  const [logline, setLogline] = useState("");
  const [body, setBody] = useState("");
  const [ending, setEnding] = useState("");
  const [status, setStatus] = useState<EditablePlanningStatus>("draft");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [arcTitle, setArcTitle] = useState("");
  const [arcType, setArcType] = useState<StoryArcType>("main");
  const [arcSummary, setArcSummary] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getStoryPlan(novelId, controller.signal),
      listChapterOutlines(novelId, controller.signal),
      listStoryArcs(novelId, controller.signal),
      listVolumeOutlines(novelId, controller.signal),
    ])
      .then(([story, rows, nextArcs, nextVolumes]) => {
        if (!active) {
          return;
        }
        setPlan(story.plan);
        applyPlan(story.plan, setLogline, setBody, setEnding, setStatus);
        setOutlines(rows);
        setArcs(nextArcs);
        setVolumeOutlines(nextVolumes);
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
  const volumeOutlineById = new Map(volumeOutlines.map((item) => [item.volume_id, item]));

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
      <StoryArcEditor
        novelId={novelId}
        arcs={arcs}
        busy={busy}
        title={arcTitle}
        arcType={arcType}
        summary={arcSummary}
        onTitle={setArcTitle}
        onType={setArcType}
        onSummary={setArcSummary}
        onBusy={setBusy}
        onError={setError}
        onMessage={setMessage}
        onChange={setArcs}
      />
      <VolumeOutlineEditor
        volumes={volumes}
        outlines={volumeOutlineById}
        busy={busy}
        onBusy={setBusy}
        onError={setError}
        onMessage={setMessage}
        onChange={setVolumeOutlines}
      />
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
  const [candidate, setCandidate] = useState<OutlineCandidatePreview | null>(null);

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
      <OutlineCandidateBox
        chapterId={chapterId}
        outlineRevision={outline?.revision}
        busy={busy}
        candidate={candidate}
        onBusy={setBusy}
        onError={setError}
        onMessage={setMessage}
        onCandidate={setCandidate}
        onAccepted={(nextOutline, nextScenes) => {
          setOutline(nextOutline);
          setDraft(outlineDraft(nextOutline));
          applyScenes(nextScenes, setScenes, setSceneDrafts);
          setReady(true);
        }}
      />
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

function StoryArcEditor({
  novelId,
  arcs,
  busy,
  title,
  arcType,
  summary,
  onTitle,
  onType,
  onSummary,
  onBusy,
  onError,
  onMessage,
  onChange,
}: {
  novelId: string;
  arcs: StoryArc[];
  busy: boolean;
  title: string;
  arcType: StoryArcType;
  summary: string;
  onTitle: (value: string) => void;
  onType: (value: StoryArcType) => void;
  onSummary: (value: string) => void;
  onBusy: (value: boolean) => void;
  onError: (value: string) => void;
  onMessage: (value: string) => void;
  onChange: (rows: StoryArc[]) => void;
}) {
  async function addArc() {
    if (title.trim() === "") {
      onError("故事线需要一个标题。");
      return;
    }
    onBusy(true);
    onError("");
    try {
      await createStoryArc(novelId, {
        arc_type: arcType,
        title: title.trim(),
        summary: blank(summary),
        status: "draft",
      });
      onChange(await listStoryArcs(novelId));
      onTitle("");
      onSummary("");
      onMessage("故事线已保存为草稿。未确认，不会当作强制事实。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "故事线没有保存。"));
    } finally {
      onBusy(false);
    }
  }

  async function saveArc(arc: StoryArc, nextTitle: string, nextSummary: string, status: EditablePlanningStatus) {
    onBusy(true);
    onError("");
    try {
      await updateStoryArc(arc.id, {
        title: nextTitle.trim(),
        summary: blank(nextSummary),
        arc_type: arc.arc_type,
        status,
        expected_revision: arc.revision,
      });
      onChange(await listStoryArcs(novelId));
      onMessage("故事线已保存。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "故事线没有保存。"));
    } finally {
      onBusy(false);
    }
  }

  async function confirmArc(arc: StoryArc) {
    onBusy(true);
    onError("");
    try {
      await confirmStoryArc(arc.id, arc.revision);
      onChange(await listStoryArcs(novelId));
      onMessage("故事线已确认。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "故事线没有确认。"));
    } finally {
      onBusy(false);
    }
  }

  async function removeArc(arc: StoryArc) {
    if (!window.confirm(`删除故事线「${arc.title}」？`)) {
      return;
    }
    onBusy(true);
    onError("");
    try {
      await deleteStoryArc(arc.id);
      onChange(await listStoryArcs(novelId));
      onMessage("故事线已删除。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "故事线没有删除。"));
    } finally {
      onBusy(false);
    }
  }

  async function moveArc(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= arcs.length) {
      return;
    }
    const ids = arcs.map((arc) => arc.id);
    const current = ids[index];
    const next = ids[target];
    if (!current || !next) {
      return;
    }
    ids[index] = next;
    ids[target] = current;
    onBusy(true);
    onError("");
    try {
      onChange(await reorderStoryArcs(novelId, ids));
      onMessage("故事线顺序已保存。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "故事线顺序没有保存。"));
    } finally {
      onBusy(false);
    }
  }

  return (
    <section className="plan-form" aria-label="故事线">
      <h3>故事线</h3>
      <p className="hint">主线、支线和人物线都属于这本作品。草稿不会被当作事实。</p>
      {arcs.length === 0 ? <p className="hint">还没有故事线。</p> : null}
      {arcs.map((arc, index) => (
        <ArcRow
          key={`${arc.id}:${arc.revision}:${arc.sort_order}`}
          arc={arc}
          index={index}
          total={arcs.length}
          busy={busy}
          onSave={saveArc}
          onConfirm={confirmArc}
          onDelete={removeArc}
          onMove={moveArc}
        />
      ))}
      <label>
        新故事线标题
        <input
          aria-label="新故事线标题"
          value={title}
          maxLength={200}
          onChange={(event) => {
            onTitle(event.target.value);
          }}
        />
      </label>
      <label>
        类型
        <select
          aria-label="新故事线类型"
          value={arcType}
          onChange={(event) => {
            onType(event.target.value as StoryArcType);
          }}
        >
          {(Object.keys(STORY_ARC_TYPE_LABEL) as StoryArcType[]).map((item) => (
            <option key={item} value={item}>
              {STORY_ARC_TYPE_LABEL[item]}
            </option>
          ))}
        </select>
      </label>
      <label>
        摘要
        <textarea
          aria-label="新故事线摘要"
          value={summary}
          maxLength={4000}
          onChange={(event) => {
            onSummary(event.target.value);
          }}
        />
      </label>
      <button className="primary" type="button" disabled={busy} onClick={() => void addArc()}>
        添加故事线
      </button>
    </section>
  );
}

function ArcRow({
  arc,
  index,
  total,
  busy,
  onSave,
  onConfirm,
  onDelete,
  onMove,
}: {
  arc: StoryArc;
  index: number;
  total: number;
  busy: boolean;
  onSave: (
    arc: StoryArc,
    title: string,
    summary: string,
    status: EditablePlanningStatus,
  ) => Promise<void>;
  onConfirm: (arc: StoryArc) => Promise<void>;
  onDelete: (arc: StoryArc) => Promise<void>;
  onMove: (index: number, direction: -1 | 1) => Promise<void>;
}) {
  const [title, setTitle] = useState(arc.title);
  const [summary, setSummary] = useState(arc.summary ?? "");
  const [status, setStatus] = useState<EditablePlanningStatus>(editableStatus(arc.status));

  return (
    <form
      className="scene-card"
      onSubmit={(event) => {
        event.preventDefault();
        void onSave(arc, title, summary, status);
      }}
    >
      <StatusBadge status={arc.status} countsAsFact={arc.counts_as_fact} />
      <p className="hint">{STORY_ARC_TYPE_LABEL[arc.arc_type]}</p>
      <label>
        标题
        <input
          aria-label={`故事线标题 ${arc.title}`}
          value={title}
          maxLength={200}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      </label>
      <label>
        摘要
        <textarea
          aria-label={`故事线摘要 ${arc.title}`}
          value={summary}
          maxLength={4000}
          onChange={(event) => {
            setSummary(event.target.value);
          }}
        />
      </label>
      <label>
        保存后的状态
        <select
          aria-label={`故事线状态 ${arc.title}`}
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
          保存故事线
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy || arc.status === "confirmed"}
          onClick={() => {
            void onConfirm(arc);
          }}
        >
          确认故事线
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy || index === 0}
          onClick={() => {
            void onMove(index, -1);
          }}
        >
          上移故事线
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy || index === total - 1}
          onClick={() => {
            void onMove(index, 1);
          }}
        >
          下移故事线
        </button>
        <button
          className="ghost danger"
          type="button"
          disabled={busy}
          onClick={() => {
            void onDelete(arc);
          }}
        >
          删除故事线
        </button>
      </div>
    </form>
  );
}

function VolumeOutlineEditor({
  volumes,
  outlines,
  busy,
  onBusy,
  onError,
  onMessage,
  onChange,
}: {
  volumes: Volume[];
  outlines: Map<string, VolumeOutline>;
  busy: boolean;
  onBusy: (value: boolean) => void;
  onError: (value: string) => void;
  onMessage: (value: string) => void;
  onChange: (rows: VolumeOutline[]) => void;
}) {
  return (
    <section aria-label="卷大纲">
      <h3>卷大纲</h3>
      <p className="hint">每卷一份。保存卷大纲不会改卷名，也不会改章节正文修订。</p>
      {volumes.length === 0 ? <p className="hint">还没有卷。先在目录里新建卷，再写卷大纲。</p> : null}
      {volumes.map((volume) => {
        const outline = outlines.get(volume.id) ?? null;
        return (
        <VolumeOutlineForm
          key={`${volume.id}:${outline?.revision ?? 0}:${outline?.status ?? "none"}`}
          volume={volume}
          outline={outline}
          busy={busy}
          onBusy={onBusy}
          onError={onError}
          onMessage={onMessage}
          onChange={onChange}
        />
        );
      })}
    </section>
  );
}

function VolumeOutlineForm({
  volume,
  outline,
  busy,
  onBusy,
  onError,
  onMessage,
  onChange,
}: {
  volume: Volume;
  outline: VolumeOutline | null;
  busy: boolean;
  onBusy: (value: boolean) => void;
  onError: (value: string) => void;
  onMessage: (value: string) => void;
  onChange: (rows: VolumeOutline[]) => void;
}) {
  const [goal, setGoal] = useState(outline?.goal ?? "");
  const [events, setEvents] = useState(outline?.key_events ?? "");
  const [startState, setStartState] = useState(outline?.start_state ?? "");
  const [endState, setEndState] = useState(outline?.end_state ?? "");
  const [status, setStatus] = useState<EditablePlanningStatus>(
    editableStatus(outline?.status ?? "draft"),
  );

  async function save() {
    onBusy(true);
    onError("");
    try {
      await saveVolumeOutline(volume.id, {
        goal: blank(goal),
        key_events: blank(events),
        start_state: blank(startState),
        end_state: blank(endState),
        status,
        expected_revision: outline?.revision,
      });
      onChange(await listVolumeOutlines(volume.novel_id));
      onMessage("卷大纲已保存。未确认时不会当作事实。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "卷大纲没有保存。"));
    } finally {
      onBusy(false);
    }
  }

  async function confirm() {
    if (!outline) {
      onError("先保存卷大纲，再确认。");
      return;
    }
    onBusy(true);
    onError("");
    try {
      await confirmVolumeOutline(volume.id, outline.revision);
      onChange(await listVolumeOutlines(volume.novel_id));
      onMessage("卷大纲已确认。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "卷大纲没有确认。"));
    } finally {
      onBusy(false);
    }
  }

  return (
    <form
      className="plan-form"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <h4>{volume.title}</h4>
      <StatusBadge status={outline?.status ?? null} countsAsFact={outline?.counts_as_fact ?? false} />
      <label>
        卷目标
        <input
          aria-label={`${volume.title}的卷目标`}
          value={goal}
          maxLength={500}
          onChange={(event) => {
            setGoal(event.target.value);
          }}
        />
      </label>
      <label>
        关键事件
        <textarea
          aria-label={`${volume.title}的关键事件`}
          value={events}
          maxLength={4000}
          onChange={(event) => {
            setEvents(event.target.value);
          }}
        />
      </label>
      <label>
        起始状态
        <textarea
          aria-label={`${volume.title}的起始状态`}
          value={startState}
          maxLength={2000}
          onChange={(event) => {
            setStartState(event.target.value);
          }}
        />
      </label>
      <label>
        结束状态
        <textarea
          aria-label={`${volume.title}的结束状态`}
          value={endState}
          maxLength={2000}
          onChange={(event) => {
            setEndState(event.target.value);
          }}
        />
      </label>
      <label>
        保存后的状态
        <select
          aria-label={`${volume.title}的卷大纲状态`}
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
          保存卷大纲
        </button>
        <button
          className="ghost"
          type="button"
          disabled={busy || outline === null || outline.status === "confirmed"}
          onClick={() => {
            void confirm();
          }}
        >
          确认卷大纲
        </button>
      </div>
    </form>
  );
}

function OutlineCandidateBox({
  chapterId,
  outlineRevision,
  busy,
  candidate,
  onBusy,
  onError,
  onMessage,
  onCandidate,
  onAccepted,
}: {
  chapterId: string;
  outlineRevision: number | undefined;
  busy: boolean;
  candidate: OutlineCandidatePreview | null;
  onBusy: (value: boolean) => void;
  onError: (value: string) => void;
  onMessage: (value: string) => void;
  onCandidate: (value: OutlineCandidatePreview | null) => void;
  onAccepted: (outline: ChapterOutline, scenes: SceneCard[]) => void;
}) {
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [modelId, setModelId] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    listModelConfigs(controller.signal)
      .then(setConfigs)
      .catch(() => {
        setConfigs([]);
      });
    return () => {
      controller.abort();
    };
  }, [chapterId]);

  async function preview() {
    onBusy(true);
    onError("");
    try {
      const next = modelId
        ? await previewOutlineCandidate(chapterId, modelId)
        : await previewOutlineCandidate(chapterId);
      onCandidate(next);
      onMessage(next.simulated ? "已生成模拟候选，尚未写入。" : "已生成候选，尚未写入。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "大纲候选没有生成。"));
    } finally {
      onBusy(false);
    }
  }

  async function accept() {
    if (!candidate) {
      return;
    }
    onBusy(true);
    onError("");
    try {
      const saved = await acceptOutlineCandidate(chapterId, candidate, outlineRevision);
      onAccepted(saved.outline, await listScenes(chapterId));
      onCandidate(null);
      onMessage("候选已写入草稿大纲。仍未确认，正文没有改动。");
    } catch (cause: unknown) {
      onError(messageFrom(cause, "大纲候选没有写入。"));
    } finally {
      onBusy(false);
    }
  }

  return (
    <section className="plan-form" aria-label="大纲候选">
      <h3>大纲候选</h3>
      <p className="hint">先预览。确认写入后才进入正式规划，并且只写成草稿，不改正文。</p>
      <label>
        本次模型
        <select
          aria-label="大纲候选所用模型"
          value={modelId}
          onChange={(event) => {
            setModelId(event.target.value);
          }}
        >
          <option value="">使用模拟</option>
          {configs
            .filter((item) => item.is_enabled)
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name}
                {item.is_default ? "（默认）" : ""}
              </option>
            ))}
        </select>
      </label>
      <button className="ghost" type="button" disabled={busy} onClick={() => void preview()}>
        {modelId ? "生成大纲候选" : "生成大纲候选（模拟）"}
      </button>
      {candidate ? (
        <div className="scene-card">
          <p className="plan-status">
            {candidate.simulated ? "模拟" : candidate.provider_mode} · 未确认
          </p>
          <p>{candidate.note}</p>
          <p>目标：{candidate.goal ?? "（空）"}</p>
          <p>必须推进：{candidate.must_advance ?? "（空）"}</p>
          <p>禁止揭露：{candidate.forbidden_reveals ?? "（空）"}</p>
          <p>结尾：{candidate.ending_hook ?? "（空）"}</p>
          {candidate.scenes.length > 0 ? (
            <ul>
              {candidate.scenes.map((scene, index) => (
                <li key={`${scene.goal ?? "scene"}-${index}`}>场景：{scene.goal ?? "（空）"}</li>
              ))}
            </ul>
          ) : null}
          <button className="primary" type="button" disabled={busy} onClick={() => void accept()}>
            写入草稿大纲
          </button>
        </div>
      ) : null}
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
