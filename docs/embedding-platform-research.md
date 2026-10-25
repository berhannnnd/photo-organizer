# EmbeddingGemma 2 服务平台调研

日期：2026-10-25。范围：官方文档、发布记录与对应版本源码；没有安装平台、下载权重、启动服务或进行性能实测。

## 结论

平台是否有 embeddings endpoint 与是否能编码图片是两回事。当前查到 Ollama 和 vLLM 均已有 EmbeddingGemma 2 多模态支持的明确证据；LM Studio 的公开 embedding 接口仍只明确文本输入，不能据此证明图文 embedding 支持。

| 平台 | 确认的证据 | 未确认事项 | 项目定位 |
| --- | --- | --- | --- |
| Ollama | v0.40.11 官方 api.md 的 /api/embed 示例直接使用 embeddinggemma2，input 支持 text/image/audio 对象及混合批次；v0.40.4 发布记录提到 llama-server 多模态 embedding | 示例名 embeddinggemma2 对应的公开 library 页面本次 404；实际权重获取/导入、量化及本机图文对齐待验证 | Mac 易部署后端候选，但不能直接承诺 ollama pull embeddinggemma2 可用 |
| LM Studio | /v1/embeddings 官方说明为 input text；文档中的 EmbeddingGemma 支持可追溯到早期文本版本 | 未找到 EmbeddingGemma 2 图片 embedding 的明确公开合同；聊天可看图不构成证明 | 可作文本描述 embedding 后端，暂不列为已验证原生文搜图后端 |
| vLLM | v0.32.0 发布说明明确新增 google/embeddinggemma-2 多模态 embedding，含按 limit-mm-per-prompt 跳过不用编码器；主分支 registry 注册 EmbeddingGemma2Model | 本机运行、部署命令/参数组合、吞吐与内存未测试 | Linux GPU 共享服务优先候选；具体镜像/版本固定后验收 |
| Sentence Transformers + FastAPI | Google 官方多模态指南提供图片/文本编码方式；FastAPI 自行包装服务 | 需维护接口、队列、鉴权、生命周期及资源调度；MPS 兼容性待实测 | 正确性基线与直接可控的兼容实现 |

## 对仓库的建议

1. 对外保持统一 embedding provider 合同，内部适配 Ollama 原生 /api/embed、vLLM 多模态 pooling/embedding 协议以及 Python 服务。不假装所有平台的 OpenAI-compatible /v1/embeddings 都支持同一种图片请求。
2. 普通 Mac 用户优先验证 Ollama 的模型导入和图文请求链路；失败时回到官方 Sentence Transformers 实现。Linux GPU 团队部署优先评估已明确支持模型的 vLLM 版本。
3. 模型权重、revision、量化、processor、维度、归一化、提示前缀共同组成索引身份。不能因为都叫 EmbeddingGemma 2 就直接共享不同运行后端生成的向量；迁移先验证数值/检索一致性，否则重新建索引。
4. 健康检查必须验证图像输入和文本输入，不只测一次文本向量。至少用不同图像、相关中文描述、无关描述和反例验证维度、有限值、内容敏感性、跨模态排序及批量顺序。
5. 测试冷启动、热查询、批量图片编码、内存，以及索引进行中的查询尾延迟。平台支持并发不等于自动实现查询优先；引擎应限制后台批次并进行调度。
6. PRD 评审暂停仍然有效。本次结果是资料支持结论，不是部署验收。

## 官方来源

- Ollama v0.40.11 API（包含 multimodal input 示例）：https://github.com/ollama/ollama/blob/v0.40.11/docs/api.md
- Ollama v0.40.4 发布记录：https://github.com/ollama/ollama/releases/tag/v0.40.4
- Ollama v0.40.11 发布记录：https://github.com/ollama/ollama/releases/tag/v0.40.11
- 第一代文本模型页面：https://ollama.com/library/embeddinggemma
- 本次未能取得的第二代同名示例 library 页：https://ollama.com/library/embeddinggemma2 （HTTP 404，不代表无法导入运行）
- LM Studio embeddings：https://lmstudio.ai/docs/developer/openai-compat/embeddings
- vLLM v0.32.0 发布记录：https://github.com/vllm-project/vllm/releases/tag/v0.32.0
- vLLM 模型注册：https://github.com/vllm-project/vllm/blob/main/vllm/model_executor/models/registry.py
- vLLM 模型实现：https://github.com/vllm-project/vllm/blob/main/vllm/model_executor/models/embedding_gemma2.py
- Google 官方多模态推理指南：https://ai.google.dev/gemma/docs/embeddinggemma/multimodal-embeddinggemma-with-sentence-transformers
