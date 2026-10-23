import { useEffect, useState, type FormEvent } from "react";
import {
  createModelConfig,
  deleteModelConfig,
  listModelConfigs,
  listProviderPresets,
  setDefaultModelConfig,
  testModelConfig,
  testSavedModelConfig,
  updateModelConfig,
  type ProviderPreset,
} from "../api/models.ts";
import { ApiError, type ModelConfig, type ModelConfigInput, type ModelTestStatus, type ProviderType } from "../api/types.ts";
import { confirmDialog } from "../components/ConfirmDialog.tsx";
import { ThemeSwitcher } from "../components/ThemeSwitcher.tsx";
import { baseUrlAfterPresetChange, parseHeaderLines } from "../modelPresets.ts";

const EMPTY: ModelConfigInput = {
  display_name: "",
  provider: "custom",
  provider_type: "openai_compatible",
  base_url: "",
  model_name: "",
  api_key: "",
  timeout_seconds: 60,
  max_retries: 2,
  temperature: 0.8,
  max_output_tokens: 1200,
  supports_streaming: true,
  supports_json_output: false,
  is_enabled: true,
};

const STATUS_LABEL: Record<ModelTestStatus, string> = {
  untested: "未测试",
  success: "成功",
  failed: "失败",
  stale: "配置已变更，需重新测试",
};

export function ModelSettingsPage() {
  const [configs, setConfigs] = useState<ModelConfig[] | null>(null);
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [draft, setDraft] = useState<ModelConfigInput>(EMPTY);
  const [headerText, setHeaderText] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setConfigs(await listModelConfigs());
  }

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listModelConfigs(controller.signal), listProviderPresets(controller.signal)])
      .then(([rows, nextPresets]) => {
        setConfigs(rows);
        setPresets(nextPresets);
      })
      .catch((cause: unknown) => {
        if (isAbort(cause)) {
          return;
        }
        setError(cause instanceof ApiError ? cause.message : "无法读取模型配置。");
      });
    return () => {
      controller.abort();
    };
  }, []);

  function edit(config: ModelConfig) {
    setEditingId(config.id);
    setClearKey(false);
    setHeaderText("");
    setDraft({
      display_name: config.display_name,
      provider: config.provider || "custom",
      provider_type: config.provider_type,
      base_url: config.base_url === "mock://local" ? "" : config.base_url,
      model_name: config.model_name,
      api_key: "",
      timeout_seconds: numberParam(config.parameters.timeout_seconds, 60),
      max_retries: numberParam(config.parameters.max_retries, 2),
      temperature: config.parameters.temperature === undefined ? 0.8 : numberOrNull(config.parameters.temperature),
      max_output_tokens: numberOrNull(config.parameters.max_output_tokens) ?? 1200,
      supports_streaming: config.capabilities.supports_streaming !== false,
      supports_json_output: config.capabilities.supports_json_output === true,
      is_enabled: config.is_enabled,
    });
    const headerNote = config.custom_header_names.length
      ? `已保存 Header：${config.custom_header_names.join("、")}。留空则保持。`
      : "还没有自定义 Header。";
    setNotice(config.api_key_hint ? `已保存的密钥尾号 ${config.api_key_hint}。${headerNote}` : `还没有保存密钥。${headerNote}`);
    setError("");
  }

  function onPreset(nextId: string) {
    const next = presets.find((item) => item.id === nextId);
    if (!next) {
      setDraft({ ...draft, provider: nextId });
      return;
    }
    const base_url = baseUrlAfterPresetChange(draft.base_url, draft.provider, next, presets);
    setDraft({ ...draft, provider: next.id, base_url });
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const payload = toPayload(draft, editingId !== null, headerText, clearKey);
      if (editingId) {
        await updateModelConfig(editingId, payload);
        setNotice("已更新模型配置。页面不会显示完整密钥。");
      } else {
        await createModelConfig(payload);
        setNotice("已保存模型配置。页面不会显示完整密钥。");
        setDraft(EMPTY);
        setHeaderText("");
      }
      setClearKey(false);
      await refresh();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : messageFrom(cause, "保存没有完成。"));
    } finally {
      setBusy(false);
    }
  }

  async function onTest() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const saved = editingId ? configs?.find((item) => item.id === editingId) : undefined;
      const unchanged =
        saved !== undefined &&
        !draft.api_key &&
        !clearKey &&
        headerText.trim() === "" &&
        draft.base_url.trim().replace(/\/+$/, "") === saved.base_url.replace(/\/+$/, "") &&
        draft.model_name.trim() === saved.model_name &&
        draft.provider_type === saved.provider_type;
      const result = unchanged && editingId
        ? await testSavedModelConfig(editingId)
        : await testModelConfig({
            config_id: editingId ?? undefined,
            provider_type: draft.provider_type,
            base_url: draft.base_url,
            model_name: draft.model_name,
            api_key: draft.api_key || undefined,
            timeout_seconds: draft.timeout_seconds,
          });
      const prefix = result.provider_mode === "mock" ? "模拟：" : "";
      setNotice(`${prefix}${result.message}`);
      await refresh();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "连接测试没有完成。");
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function onDelete(config: ModelConfig) {
    if (!(await confirmDialog(`删除模型「${config.display_name}」？已生成的任务记录会保留。`, { tone: "danger" }))) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      await deleteModelConfig(config.id);
      if (editingId === config.id) {
        setEditingId(null);
        setDraft(EMPTY);
      }
      await refresh();
      setNotice("已删除模型配置。");
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "删除没有完成。");
    } finally {
      setBusy(false);
    }
  }

  async function onDefault(config: ModelConfig) {
    setBusy(true);
    setError("");
    try {
      await setDefaultModelConfig(config.id);
      await refresh();
      setNotice(`已把「${config.display_name}」设为默认模型。`);
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "没能设为默认。");
    } finally {
      setBusy(false);
    }
  }

  async function onTestSaved(config: ModelConfig) {
    setBusy(true);
    setError("");
    try {
      const result = await testSavedModelConfig(config.id);
      setNotice(result.message);
      await refresh();
    } catch (cause: unknown) {
      setError(cause instanceof ApiError ? cause.message : "连接测试没有完成。");
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const presetHint = presets.find((item) => item.id === draft.provider)?.hint ?? "";

  return (
    <div className="page settings-page">
      <header className="topbar">
        <div>
          <a className="ghost" href="#/">
            返回作品库
          </a>
          <h1>模型配置</h1>
        </div>
        <ThemeSwitcher />
      </header>
      <p className="hint">
        密钥和自定义 Header 只保存在服务器上，并用主密钥加密。保存之后，页面只显示已配置状态、Header 名称或密钥尾号。
        只有测试成功的配置可以设为默认。改了地址、模型、密钥或关键参数之后，需要重新测试。
      </p>
      {error ? (
        <p className="banner banner-error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="banner" role="status">
          {notice}
        </p>
      ) : null}
      <div className="settings-layout">
      <form className="stack-form" onSubmit={(event) => void onSubmit(event)}>
        <label>
          显示名称
          <input
            value={draft.display_name}
            required
            maxLength={200}
            onChange={(event) => {
              setDraft({ ...draft, display_name: event.target.value });
            }}
          />
        </label>
        <label>
          服务商
          <select
            aria-label="服务商"
            value={draft.provider}
            onChange={(event) => {
              onPreset(event.target.value);
            }}
          >
            {presets.length === 0 ? <option value={draft.provider}>{draft.provider}</option> : null}
            {presets.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>
        {presetHint ? <p className="hint">{presetHint}</p> : null}
        <label>
          接口类型
          <select
            aria-label="接口类型"
            value={draft.provider_type}
            onChange={(event) => {
              setDraft({ ...draft, provider_type: event.target.value as ProviderType });
            }}
          >
            <option value="openai_compatible">OpenAI 兼容 Chat Completions</option>
            <option value="mock">模拟</option>
          </select>
        </label>
        <label>
          Base URL
          <input
            aria-label="Base URL"
            value={draft.base_url}
            placeholder="https://example.com/v1"
            onChange={(event) => {
              setDraft({ ...draft, base_url: event.target.value });
            }}
          />
        </label>
        <label>
          模型标识
          <input
            aria-label="模型标识"
            value={draft.model_name}
            required
            maxLength={200}
            onChange={(event) => {
              setDraft({ ...draft, model_name: event.target.value });
            }}
          />
        </label>
        <label>
          API Key
          <input
            type="password"
            autoComplete="off"
            value={draft.api_key ?? ""}
            placeholder={editingId ? "留空则保持已保存的密钥" : "只在保存时提交"}
            onChange={(event) => {
              setClearKey(false);
              setDraft({ ...draft, api_key: event.target.value });
            }}
          />
        </label>
        {editingId ? (
          <label className="check-row">
            <input
              type="checkbox"
              checked={clearKey}
              onChange={(event) => {
                setClearKey(event.target.checked);
                if (event.target.checked) {
                  setDraft({ ...draft, api_key: "" });
                }
              }}
            />
            清除已保存的密钥
          </label>
        ) : null}
        <label>
          超时（秒）
          <input
            type="number"
            min={1}
            max={300}
            value={draft.timeout_seconds}
            onChange={(event) => {
              setDraft({ ...draft, timeout_seconds: Number(event.target.value) });
            }}
          />
        </label>
        <label>
          默认温度
          <input
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={draft.temperature ?? ""}
            onChange={(event) => {
              setDraft({
                ...draft,
                temperature: event.target.value === "" ? null : Number(event.target.value),
              });
            }}
          />
        </label>
        <label>
          默认最大输出
          <input
            type="number"
            min={1}
            max={32000}
            value={draft.max_output_tokens ?? ""}
            onChange={(event) => {
              setDraft({
                ...draft,
                max_output_tokens: event.target.value === "" ? null : Number(event.target.value),
              });
            }}
          />
        </label>
        <label>
          自定义 Header
          <textarea
            aria-label="自定义 Header"
            value={headerText}
            placeholder={"X-Title: novel\n留空则保持已保存的 Header"}
            onChange={(event) => {
              setHeaderText(event.target.value);
            }}
          />
        </label>
        <label className="check-row">
          <input
            type="checkbox"
            checked={draft.is_enabled}
            onChange={(event) => {
              setDraft({ ...draft, is_enabled: event.target.checked });
            }}
          />
          启用
        </label>
        <div className="inline-actions">
          <button className="primary" type="submit" disabled={busy}>
            {editingId ? "保存修改" : "添加模型"}
          </button>
          <button className="ghost" type="button" disabled={busy} onClick={() => void onTest()}>
            测试连接
          </button>
          {editingId ? (
            <button
              className="ghost"
              type="button"
              disabled={busy}
              onClick={() => {
                setEditingId(null);
                setDraft(EMPTY);
                setHeaderText("");
                setClearKey(false);
                setNotice("");
              }}
            >
              取消编辑
            </button>
          ) : null}
        </div>
      </form>
      <section aria-labelledby="saved-models">
        <h2 id="saved-models">已保存的模型</h2>
        {configs === null ? <p role="status">正在读取模型配置</p> : null}
        {configs?.length === 0 ? <p className="hint">还没有模型。不配置也可以用模拟模型试运行。</p> : null}
        <ul className="settings-list">
          {configs?.map((config) => (
            <li key={config.id}>
              <div>
                <p>
                  {config.display_name}
                  {config.is_default ? " · 默认" : ""}
                  {config.provider_type === "mock" ? " · 模拟" : ""}
                  {config.is_enabled ? "" : " · 已停用"}
                </p>
                <p className="hint">
                  {config.provider} · {config.model_name}
                  {config.base_url ? ` · ${config.base_url}` : ""}
                </p>
                <p className="hint">
                  状态：{STATUS_LABEL[config.last_test_status]}
                  {config.last_test_error_code ? ` · ${config.last_test_error_code}` : ""}
                </p>
                <p className="hint">
                  {config.api_key_configured ? `密钥已配置 ${config.api_key_hint ?? ""}` : "未保存密钥"}
                </p>
              </div>
              <div className="inline-actions">
                <button className="ghost" type="button" disabled={busy} onClick={() => edit(config)}>
                  编辑
                </button>
                <button className="ghost" type="button" disabled={busy} onClick={() => void onTestSaved(config)}>
                  测试
                </button>
                <button
                  className="ghost"
                  type="button"
                  disabled={busy || config.last_test_status !== "success" || config.is_default}
                  onClick={() => void onDefault(config)}
                >
                  设为默认
                </button>
                <button
                  className="ghost danger"
                  type="button"
                  disabled={busy}
                  onClick={() => void onDelete(config)}
                >
                  删除
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>
      </div>
    </div>
  );
}

function toPayload(
  draft: ModelConfigInput,
  editing: boolean,
  headerText: string,
  clearKey: boolean,
): ModelConfigInput {
  const payload: ModelConfigInput = {
    ...draft,
    display_name: draft.display_name.trim(),
    base_url: draft.base_url.trim(),
    model_name: draft.model_name.trim(),
  };
  if (clearKey) {
    payload.clear_api_key = true;
    delete payload.api_key;
  } else if (!payload.api_key) {
    if (editing || payload.provider_type === "mock") {
      delete payload.api_key;
    }
  }
  if (headerText.trim()) {
    payload.custom_headers = parseHeaderLines(headerText);
  }
  return payload;
}

function numberParam(value: unknown, fallback: number): number {
  return typeof value === "number" ? value : fallback;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}
