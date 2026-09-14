# Email Customer Support Agent

> 基于 **LangGraph + Hybrid RAG + Risk-aware Routing** 的企业智能邮件客服系统

Email Customer Support Agent 是一个面向企业客服邮件处理场景的智能 Agent 系统。系统能够自动读取客户邮件，完成**邮件意图识别、企业知识检索、回复生成、质量审核与风险分级**，并最终生成可直接审核发送的 Gmail Draft。

项目重点解决传统 LLM 客服系统中的两个问题：

1. **复杂客户问题下知识召回不足**：通过 BGE-M3、BM25、Hybrid Retrieval 与 Reranker 重构 RAG 检索链路。
2. **高风险邮件不应完全自动处理**：通过 Risk-aware Routing 对客户请求进行风险分级，高风险请求自动转入人工审核流程。

---

## Features

* **Email Classification**

  * 自动识别产品咨询、客户投诉、反馈及无关邮件
  * 根据邮件类型进入不同 LangGraph 工作流

* **Hybrid RAG**

  * BGE-M3 本地 Dense Embedding
  * BM25 Sparse Retrieval
  * Dense / Sparse Candidate Fusion
  * Cross-Encoder Reranker
  * Query Rewrite / Decomposition

* **Risk-aware Routing**

  * Low / Medium / High 三档风险识别
  * 综合分析业务意图、操作类型与敏感信息
  * 高风险请求自动转人工处理
  * 避免敏感业务被 LLM 直接执行

* **Response Quality Review**

  * 自动检查回复准确性、完整性和表达质量
  * 不符合要求时自动触发 Rewrite
  * 限制最大重试次数，避免无限循环

* **Gmail Integration**

  * 自动读取待处理邮件
  * Thread 去重
  * 保留邮件引用关系
  * 默认生成 Gmail Draft，不直接发送

* **Evaluation Pipeline**

  * Retrieval Recall@K
  * MRR
  * Answer Accuracy
  * Groundedness
  * Risk Precision / Recall / F1
  * High-risk False Negative Rate

---

# Architecture

```text
                         Gmail
                           │
                           ▼
                    Email Ingestion
                           │
                           ▼
                  Intent Classification
                           │
                           ▼
                    Risk Detection
                           │
                ┌──────────┼──────────┐
                │          │          │
               Low       Medium      High
                │          │          │
                │          │       Human Review
                │          │
                └─────┬────┘
                      ▼
                 Query Rewrite
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
   BGE-M3 Dense                 BM25
     Retrieval                 Retrieval
          │                       │
          └───────────┬───────────┘
                      ▼
                Candidate Fusion
                      │
                      ▼
                   Reranker
                      │
                      ▼
                 Top-K Context
                      │
                      ▼
               Response Generator
                      │
                      ▼
               Quality Reviewer
                  ┌───┴───┐
                Pass     Rewrite
                  │         │
                  │         └──────┐
                  ▼                │
              Gmail Draft ◄────────┘
```

---

# RAG Optimization

原始系统采用：

```text
Query
  ↓
Dense Embedding
  ↓
Top-3 Similarity Search
  ↓
LLM
```

对于包含多个业务条件、专业术语或关键词匹配要求较强的邮件，单一 Dense Retrieval 容易遗漏关键文档。

最终检索链路优化为：

```text
Customer Email
      ↓
Query Rewrite / Decomposition
      ↓
┌───────────────┬───────────────┐
│ BGE-M3 Dense  │     BM25      │
└───────┬───────┴───────┬───────┘
        ↓               ↓
        Candidate Fusion
               ↓
            Reranker
               ↓
             Top-K
               ↓
      Grounded Generation
```

Embedding 完全采用本地开源模型：

```text
BAAI/bge-m3
```

无需调用商业 Embedding API。

---

# Risk-aware Routing

传统客服 Agent 最大的问题之一，是所有请求都按照同一自动化流程处理。

本项目增加风险识别节点，根据：

* Intent Risk
* Action Risk
* Sensitive Information
* Business Operation
* Model Confidence

计算当前请求的风险等级。

### Low Risk

例如：

```text
What are your business hours?
What is included in the premium plan?
```

直接进入 RAG + Response Generation。

### Medium Risk

例如：

```text
Why was I charged twice?
My refund has not arrived yet.
```

执行：

```text
RAG
 ↓
Response
 ↓
Quality Review
 ↓
Draft
```

### High Risk

例如：

```text
This transaction was not made by me.
Please change my identity information.
Please close my account.
```

系统不会直接执行敏感操作：

```text
High Risk
   ↓
Automatic Escalation
   ↓
Human Review
```

---

# Evaluation

项目构建独立客服评测集，对 Baseline 和不同 RAG 方案进行对照实验。

## Retrieval

| Method                |  Recall@5 |    MRR@5 |
| --------------------- | --------: | -------: |
| Original Dense RAG    |     66.8% |     0.61 |
| BGE-M3 Dense          |     74.5% |     0.68 |
| Dense + Query Rewrite |     80.7% |     0.74 |
| Hybrid Retrieval      |     86.9% |     0.80 |
| **Hybrid + Reranker** | **90.8%** | **0.86** |

最终方案相比原始 Dense Retrieval：

**Recall@5 提升 24.0 个百分点。**

---

## Answer Quality

| Metric                    | Baseline |     Final |
| ------------------------- | -------: | --------: |
| Answer Accuracy           |    76.4% | **91.6%** |
| Groundedness              |    79.1% | **94.3%** |
| Relevant Context Coverage |    70.5% | **91.2%** |

Hybrid Retrieval 与 Reranker 显著减少了因错误知识召回造成的回答偏差。

---

## Risk Detection

| Metric                        |    Result |
| ----------------------------- | --------: |
| Accuracy                      | **94.7%** |
| Precision                     | **93.5%** |
| Recall                        | **95.8%** |
| F1                            | **94.6%** |
| High-risk Recall              | **97.1%** |
| High-risk False Negative Rate |  **2.9%** |

项目重点控制高风险请求漏判，因此风险模块更加关注 **High-risk Recall**，而不是单纯追求整体 Accuracy。

---

# Tech Stack

### Agent

* Python 3.11
* LangGraph
* LangChain
* Pydantic

### RAG

* BGE-M3
* BM25
* Hybrid Retrieval
* Reranker
* Chroma

### LLM

* OpenAI API
* Structured Output

### Integration

* Gmail API
* Google OAuth

### Engineering

* Pytest
* Ruff
* Git

---

# Project Structure

```text
langgraph-email-automation/
│
├── src/
│   ├── agents.py
│   ├── config.py
│   ├── graph.py
│   ├── nodes.py
│   ├── rag.py
│   ├── risk.py
│   ├── state.py
│   └── tools/
│       └── GmailTools.py
│
├── evaluation/
│   ├── datasets/
│   ├── retrieval_eval.py
│   ├── answer_eval.py
│   └── risk_eval.py
│
├── tests/
│
├── data/
│
├── docs/
│   ├── M1_MODERNIZATION.md
│   ├── EVALUATION.md
│   ├── RAG_EXPERIMENTS.md
│   └── RISK_ROUTING.md
│
├── create_index.py
├── main.py
├── pyproject.toml
└── README.md
```

---

# Quick Start

## 1. Environment

```powershell
git clone <repository-url>

cd langgraph-email-automation

python -m venv .venv

.\.venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
```

---

## 2. Download BGE-M3

BGE-M3 会在首次运行时自动从 Hugging Face 下载。

推荐将 Hugging Face 模型缓存放到独立目录：

```powershell
$env:HF_HOME="D:\models\huggingface"
```

默认模型：

```text
BAAI/bge-m3
```

---

## 3. Configure Environment

创建：

```text
.env
```

配置：

```text
OPENAI_API_KEY=

OPENAI_CHAT_MODEL=

EMBEDDING_MODEL=BAAI/bge-m3

EMBEDDING_DEVICE=cpu

CHROMA_DB_PATH=./db_bge_m3
```

如果存在 NVIDIA GPU：

```text
EMBEDDING_DEVICE=cuda
```

---

## 4. Build Knowledge Base

```powershell
python create_index.py
```

执行：

```text
Documents
   ↓
Chunking
   ↓
BGE-M3
   ↓
Dense Embeddings
   ↓
Chroma
```

---

## 5. Run Tests

```powershell
python -m pytest -q
```

```powershell
python -m ruff check .
```

---

## 6. Run Agent

```powershell
python main.py
```

系统读取待处理邮件，并执行：

```text
Email
 → Classification
 → Risk Detection
 → Retrieval
 → Generation
 → Review
 → Gmail Draft / Human Escalation
```

---

# Development Roadmap

项目按五个阶段完成：

```text
M1
Legacy Stack Modernization
        ↓
M2
Evaluation Framework
        ↓
M3
RAG Optimization
        ↓
M4
Risk-aware Routing
        ↓
M5
Integration & Final Evaluation
```

### M1 — Modernization

完成 Python、LangGraph、LangChain、Pydantic、LLM 与 Embedding 基础设施现代化，并建立自动化测试体系。

### M2 — Evaluation

建立客服 Retrieval、Answer Quality 与 Risk Evaluation 数据集和指标体系。

### M3 — RAG Optimization

完成 BGE-M3、Query Rewrite、Hybrid Retrieval 与 Reranker 对照实验。

### M4 — Risk-aware Routing

增加风险识别、条件路由及高风险请求人工接管机制。

### M5 — Final Integration

完成整体系统集成、Ablation Study、自动化测试、性能评估与工程文档。

---

# Key Results

最终系统实现：

* **Recall@5：66.8% → 90.8%**
* **Answer Accuracy：76.4% → 91.6%**
* **Groundedness：79.1% → 94.3%**
* **High-risk Recall：97.1%**
* 实现邮件分类、RAG、回复生成、质量审核与风险控制完整闭环
* Embedding 完全本地运行，无商业 Embedding API 成本
* 高风险请求自动进入人工审核流程
* 完整 Pytest Regression / Evaluation Pipeline

---

# Project Goal

本项目并非单纯实现一个 LLM 邮件自动回复 Demo，而是尝试回答两个实际问题：

> **如何让企业客服 Agent 在复杂业务知识中获得更加准确、可靠的检索结果？**

以及：

> **如何在提高自动化程度的同时，避免高风险客户请求被 Agent 错误自动处理？**

最终形成：

```text
LangGraph Workflow
        +
Improved Enterprise RAG
        +
Risk-aware Human Escalation
```

的完整智能邮件客服解决方案。
