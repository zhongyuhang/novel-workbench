import type { PortablePreview } from "../api/portable.ts";

type LibraryMaintenanceProps = {
  latestSuccessAt: string | null;
  backupPending: boolean;
  onBackup: () => void;
  preview: PortablePreview | null;
  previewError: string;
  importPending: boolean;
  onChooseFile: (file: File) => void;
  onConfirmImport: () => void;
  onCancelPreview: () => void;
};

export function LibraryMaintenance({
  latestSuccessAt,
  backupPending,
  onBackup,
  preview,
  previewError,
  importPending,
  onChooseFile,
  onConfirmImport,
  onCancelPreview,
}: LibraryMaintenanceProps) {
  return (
    <section className="maintenance" aria-labelledby="maintenance-heading">
      <div className="library-toolbar">
        <h2 id="maintenance-heading">备份与作品包</h2>
        <div className="inline-actions">
          <button className="ghost" type="button" disabled={backupPending} onClick={onBackup}>
            {backupPending ? "正在备份" : "立即备份"}
          </button>
          <label className="ghost file-button">
            导入作品包
            <input
              type="file"
              accept=".zip,application/zip"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) {
                  onChooseFile(file);
                }
              }}
            />
          </label>
        </div>
      </div>
      <p className="hint">
        {latestSuccessAt
          ? `最近一次成功备份：${formatTime(latestSuccessAt)}。恢复仍使用命令行，不会在网页上覆盖当前库。`
          : "还没有成功的整库备份。恢复仍使用命令行，不会在网页上覆盖当前库。"}
      </p>
      <p className="hint">
        作品包可以带到另一台机器。导入会成为一本新作品，不会覆盖现有作品。模型 API Key
        不会放进包里，导入后需要重新配置。
      </p>
      {previewError ? (
        <p className="banner banner-error" role="alert">
          {previewError}
        </p>
      ) : null}
      {preview ? (
        <div className="preview-card">
          <p>
            {preview.novel_title ? `「${preview.novel_title}」` : "这份作品包"}
            {preview.can_import ? "可以导入为新作品。" : "现在不能导入。"}
          </p>
          <p className="hint">{preview.message}</p>
          <p className="hint">
            新增章节 {preview.created.chapters}，冲突编号{" "}
            {sumCounts(preview.conflicts)}，跳过模型配置 {preview.skipped.model_configs}，无效{" "}
            {sumCounts(preview.invalid)}。
          </p>
          {preview.warnings.map((warning) => (
            <p key={warning} className="hint">
              {warning}
            </p>
          ))}
          <div className="inline-actions">
            <button
              className="primary"
              type="button"
              disabled={!preview.can_import || importPending}
              onClick={onConfirmImport}
            >
              {importPending ? "正在导入" : "导入为新作品"}
            </button>
            <button className="ghost" type="button" onClick={onCancelPreview}>
              取消
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

function sumCounts(counts: PortablePreview["created"]): number {
  return Object.values(counts).reduce((total, value) => total + value, 0);
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
