export function AiPanel() {
  return (
    <aside className="workspace-pane ai-pane" aria-labelledby="ai-heading">
      <h2 id="ai-heading">写作辅助</h2>
      <p>生成、候选审阅和记忆还没有接入。</p>
      <p className="hint">这一栏不会调用模型，也不会改写正文。</p>
    </aside>
  );
}
