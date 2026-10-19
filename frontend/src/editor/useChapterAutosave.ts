import { useCallback, useEffect, useRef, useState } from "react";
import { saveChapter } from "../api/catalog.ts";
import {
  ApiError,
  type Chapter,
  type ChapterStatus,
  type SaveKind,
  type TiptapDoc,
} from "../api/types.ts";
import { canonicalJson } from "./documentText.ts";
import { interpretSaveConflict, interpretSaveSuccess } from "./saveResult.ts";

export const AUTOSAVE_DELAY_MS = 1200;

export type SavePhase = "idle" | "dirty" | "saving" | "saved" | "error" | "conflict";

export type ChapterDraftState = {
  content: TiptapDoc;
  title: string;
  status: ChapterStatus;
};

type Options = {
  chapterId: string;
  initialRevision: number;
  initialTitle: string;
  initialStatus: ChapterStatus;
  initialContent: TiptapDoc;
  getDraft: () => ChapterDraftState;
  delayMs?: number;
  onSaved: (chapter: Chapter, kind: SaveKind) => void;
  onUnsavedChange?: (unsaved: boolean) => void;
};

function isUnsavedPhase(phase: SavePhase): boolean {
  return phase === "dirty" || phase === "saving" || phase === "error" || phase === "conflict";
}

export function useChapterAutosave(options: Options) {
  const delayMs = options.delayMs ?? AUTOSAVE_DELAY_MS;
  const getDraftRef = useRef(options.getDraft);
  const onSavedRef = useRef(options.onSaved);
  const onUnsavedChangeRef = useRef(options.onUnsavedChange);
  const chapterIdRef = useRef(options.chapterId);

  const revisionRef = useRef(options.initialRevision);
  const titleBaselineRef = useRef(options.initialTitle);
  const statusBaselineRef = useRef(options.initialStatus);
  const baselineRef = useRef(canonicalJson(options.initialContent));
  const phaseRef = useRef<SavePhase>("idle");
  const failedKindRef = useRef<SaveKind>("autosave");
  const timerRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);
  const rerunRef = useRef<SaveKind | null>(null);
  const generationRef = useRef(0);

  const [phase, setPhase] = useState<SavePhase>("idle");
  const [message, setMessage] = useState("");
  const [revision, setRevision] = useState(options.initialRevision);

  const report = useCallback((next: SavePhase, nextMessage?: string) => {
    phaseRef.current = next;
    setPhase(next);
    if (nextMessage !== undefined) {
      setMessage(nextMessage);
    }
    onUnsavedChangeRef.current?.(isUnsavedPhase(next));
  }, []);

  const isDirty = useCallback(() => {
    const draft = getDraftRef.current();
    return (
      canonicalJson(draft.content) !== baselineRef.current ||
      draft.title.trim() !== titleBaselineRef.current ||
      draft.status !== statusBaselineRef.current
    );
  }, []);

  const persist = useCallback(
    async (kind: SaveKind) => {
      if (phaseRef.current === "conflict") {
        return;
      }
      if (inFlightRef.current) {
        rerunRef.current = kind === "manual" || rerunRef.current === "manual" ? "manual" : "autosave";
        return;
      }
      const draft = getDraftRef.current();
      const title = draft.title.trim();
      if (title === "") {
        failedKindRef.current = kind;
        report("error", "标题不能为空。正文仍留在编辑器里。");
        return;
      }
      if (!isDirty() && kind === "autosave") {
        if (phaseRef.current === "dirty" || phaseRef.current === "error") {
          report("saved", "已自动保存。");
        }
        return;
      }
      const requestGeneration = generationRef.current + 1;
      generationRef.current = requestGeneration;
      inFlightRef.current = true;
      report("saving", "");
      const sentContent = draft.content;
      const sentStatus = draft.status;
      const sentRevision = revisionRef.current;
      let stopFollowUp = false;
      try {
        const saved = await saveChapter(chapterIdRef.current, {
          revision: sentRevision,
          content: sentContent,
          title,
          status: sentStatus,
          content_format: "tiptap_json",
          save_kind: kind,
        });
        const latest = getDraftRef.current();
        const decision = interpretSaveSuccess({
          requestGeneration,
          latestGeneration: generationRef.current,
          savedRevision: saved.revision,
          currentRevision: revisionRef.current,
          sentCanonical: canonicalJson(sentContent),
          currentCanonical: canonicalJson(latest.content),
          sentTitle: title,
          currentTitle: latest.title.trim(),
          sentStatus,
          currentStatus: latest.status,
        });
        if (!decision.applyRevision) {
          return;
        }
        revisionRef.current = saved.revision;
        setRevision(saved.revision);
        onSavedRef.current(saved, kind);
        if (decision.markBaseline) {
          baselineRef.current = canonicalJson(latest.content);
          titleBaselineRef.current = saved.title;
          statusBaselineRef.current = saved.status;
          report("saved", kind === "manual" ? "已保存。" : "已自动保存。");
        } else {
          report("dirty", "");
        }
      } catch (error: unknown) {
        const api = error instanceof ApiError ? error : null;
        const text = api?.message ?? "保存失败。";
        failedKindRef.current = kind;
        const stale = interpretSaveConflict({
          requestGeneration,
          latestGeneration: generationRef.current,
        });
        if (stale === "ignore") {
          return;
        }
        stopFollowUp = true;
        if (api?.status === 409) {
          report(
            "conflict",
            `${text} 本地草稿还在编辑器里。自动保存不会把旧内容盖掉，也不会写成版本快照。`,
          );
        } else {
          const prefix = kind === "manual" ? "保存失败" : "自动保存失败";
          report("error", `${prefix}，正文仍留在编辑器里。${text}`);
        }
      } finally {
        inFlightRef.current = false;
        const next = rerunRef.current;
        rerunRef.current = null;
        if (next && !stopFollowUp) {
          await persist(next);
        }
      }
    },
    [isDirty, report],
  );

  const touch = useCallback(() => {
    if (phaseRef.current === "conflict") {
      return;
    }
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (!isDirty()) {
      if (!inFlightRef.current && (phaseRef.current === "dirty" || phaseRef.current === "error")) {
        report("saved");
      }
      return;
    }
    report("dirty", "");
    timerRef.current = window.setTimeout(() => {
      void persist("autosave");
    }, delayMs);
  }, [delayMs, isDirty, persist, report]);

  const saveNow = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    return persist("manual");
  }, [persist]);

  const retry = useCallback(() => persist(failedKindRef.current), [persist]);

  const noteBaseline = useCallback((content: TiptapDoc) => {
    baselineRef.current = canonicalJson(content);
  }, []);

  const adoptServer = useCallback(
    (chapter: Chapter, nextMessage: string) => {
      revisionRef.current = chapter.revision;
      setRevision(chapter.revision);
      titleBaselineRef.current = chapter.title;
      statusBaselineRef.current = chapter.status;
      baselineRef.current = canonicalJson(chapter.content);
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      report("saved", nextMessage);
    },
    [report],
  );

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
      onUnsavedChangeRef.current?.(false);
    };
  }, []);

  return {
    phase,
    message,
    revision,
    unsaved: isUnsavedPhase(phase),
    touch,
    saveNow,
    retry,
    noteBaseline,
    adoptServer,
  };
}
