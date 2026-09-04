# food_v1 评测报告

> 金标准状态：`insufficient_human_gold`。未达到人工标注规模前不计算或展示真实准确率。

## 金标准库存

- 真实内容：5/24
- 已人工确认金标准：0/24
- 已人工标注句子：0/60
- 平台：小红书 3/12；抖音 2/12
- 品类：2/5（奶茶, 轻食）
- 第二标注覆盖：无可计算样本

## Prompt 契约回归（不是生产准确率）

- 数据范围：taskbook_acceptance_fixture_only；真实公开金标准：否
- prompt_v0 契约准确率：0.5；Badcase 4 条
- prompt_v1 规则准确率：1.0；Badcase 0 条
- prompt_v1 原句回溯：1.0

## 未完成项

- 还需人工确认至少 24 篇真实公开内容和 60 个句子。
- 还需另一位标注人独立覆盖至少 20%。
- 没有授权读取模型密钥，本轮没有调用 GLM，因此不报告模型准确率、耗时或成本。
- 随机抽 10 条人工复查尚未执行。

## 契约 Badcase

- prompt_v0：‘每一口都能嚼到虾肉’ 预测=False，期望=True
- prompt_v0：‘好吃绝了’ 预测=True，期望=False
- prompt_v0：‘看起来不错’ 预测=True，期望=False
- prompt_v0：‘吃完瘦三斤’ 预测=True，期望=False
