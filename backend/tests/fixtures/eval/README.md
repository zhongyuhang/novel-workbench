# 固定评测样例

`samples.json` 里有三条虚构短句，分别对应续写、选区改写和章节摘要。它们不包含真实小说、密钥或私人地址。

`tests/test_eval_samples.py` 会读取这份文件，用仓库里的提示词函数组装提示，再交给 `MockProvider` 生成。模拟模型不访问网络。换模型或改提示词后，用同一份样例重跑：

```bash
cd backend
pytest tests/test_eval_samples.py
```

样例只检查这条链路能重复执行，并且改写提示里带有选区。它不给文笔打分。人工审阅仍看候选本身，采纳前不会写入正文。

`quality_samples.json` 是质量规则的离线样例，含会报出的正例、不该报的反例，以及有效时间无法比较的例子。由 `tests/test_quality_rules.py` 读取。这些样例不调用模型，也不写数据库。
