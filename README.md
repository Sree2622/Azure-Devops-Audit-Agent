# Azure DevOps Audit Agent

<p align="center">
  <strong>Evidence-driven AI auditing for Azure DevOps boards and sprints.</strong>
  <br />
  Adaptive investigation · Risk analysis · Sprint intelligence · Wiki reporting
</p>

<p align="center">

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js)
![FastAPI](https://img.shields.io/badge/FastAPI-0.1+-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-Agentic_AI-1C3C3C)
![Gemini](https://img.shields.io/badge/Gemini-LLM-4285F4?logo=google&logoColor=white)
![Azure DevOps](https://img.shields.io/badge/Azure_DevOps-REST_API-0078D4?logo=azuredevops&logoColor=white)

</p>

---

## Overview

**Azure DevOps Audit Agent** is an AI-assisted auditing system that analyzes Azure DevOps boards and sprints, identifies delivery risks, and produces structured audit reports that can be published to Azure DevOps Wiki.

The system combines:

**Azure DevOps REST API → Python/FastAPI → LangGraph + Gemini → Audit Engine → Azure DevOps Wiki**

Unlike a fixed checklist-based analyzer, the agent can **adapt its investigation based on the audit request and the evidence it discovers.**

> **Be flexible about what to investigate, but strict about what to claim.**

---

## ✨ Key Capabilities

| Capability | Description |
|---|---|
| 🔎 **Adaptive Investigation** | Dynamically determines what evidence to investigate |
| 📊 **Board Health** | Analyzes work-item distribution and board state |
| 🏃 **Sprint Health** | Evaluates sprint progress and delivery signals |
| ⏳ **Aging & Stalled Work** | Identifies work items that may require attention |
| 👥 **Workload Analysis** | Detects workload concentration and distribution patterns |
| 📅 **Deadline Pressure** | Evaluates available evidence around delivery pressure |
| ⚠️ **Risk Analysis** | Produces structured delivery-risk assessments |
| 🧾 **Evidence Classification** | Separates observed facts from inference and unknowns |
| 🤖 **LLM Investigation** | Uses Gemini for investigation and interpretation |
| 📐 **Deterministic Metrics** | Performs numerical calculations in Python |
| 📝 **Audit Reports** | Generates structured audit findings |
| 📚 **Wiki Publishing** | Publishes reports to Azure DevOps Wiki |
| 🔐 **Safe Operations** | Read-only analysis by default; mutations require confirmation |

---

## 🧠 Evidence-First Design

The agent deliberately separates **facts from interpretation**.

### OBSERVED

Directly supported by retrieved Azure DevOps data.

```text
OBSERVED

Work item #123 has remained in the Active state for 18 days.
```

### INFERRED

An interpretation derived from observed evidence.

```text
INFERRED

The work item may represent aging delivery work requiring attention.
```

### UNKNOWN

Information that cannot be established from available evidence.

```text
UNKNOWN

No confirmed blocker was available from the retrieved Azure DevOps data.
```

This prevents the system from inventing:

- Owners
- Deadlines
- Blockers
- Dependencies
- Severity
- Project status
- Delivery commitments

when the underlying Azure DevOps evidence does not support them.

---

## 🏗️ Architecture

```text
                         ┌──────────────────┐
                         │    Next.js UI    │
                         └────────┬─────────┘
                                  │
                                  ▼
                         ┌──────────────────┐
                         │ FastAPI /api/*   │
                         └────────┬─────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │  Azure DevOps REST  │
                       │        APIs         │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │   LangGraph +       │
                       │      Gemini         │
                       │  Adaptive Agent     │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │    Audit Engine     │
                       │                     │
                       │ Board • Sprint •     │
                       │ Risk • Workload     │
                       └──────────┬──────────┘
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │  Azure DevOps Wiki  │
                       └─────────────────────┘
```

### Request Flow

```text
User Audit Request
        │
        ▼
    DISCOVER
        │
        ▼
     TRIAGE
        │
        ▼
  INVESTIGATE
        │
        ▼
    VALIDATE
        │
        ▼
     ASSESS
        │
        ▼
     REPORT
```

The investigation can adapt based on:

- The user's audit request
- Discovered evidence
- Board state
- Sprint state
- Available Azure DevOps data

---

## 🧩 Project Structure

```text
Azure-Devops-Audit-Agent/
│
├── agent/
│   ├── adaptive_audit.py     # Adaptive investigation
│   ├── audit.py              # Audit orchestration & reporting
│   ├── board_review.py       # Board analysis
│   ├── config.py             # Configuration
│   ├── graph.py              # LangGraph workflow
│   ├── main.py               # Agent entry point
│   ├── model.py              # Model integration
│   ├── prompts.py            # Agent prompts
│   ├── sprint_health.py      # Sprint analysis
│   ├── state.py              # Shared state
│   ├── tools.py              # Azure DevOps tools
│   └── wiki.py               # Wiki publishing
│
├── api/
│   └── index.py              # FastAPI entry point
│
├── app/
│   ├── globals.css           # Global styles
│   ├── layout.tsx            # Next.js layout
│   └── page.tsx              # Main UI
│
├── azure_agent/              # Supporting/legacy project components
│
├── package.json
├── requirements.txt
├── pyproject.toml
├── next.config.ts
├── tsconfig.json
├── .python-version
└── README.md
```

### Core Components

| Component | Responsibility |
|---|---|
| `adaptive_audit.py` | Adaptive audit investigation |
| `audit.py` | Audit orchestration and reporting |
| `board_review.py` | Board-level analysis |
| `sprint_health.py` | Sprint health analysis |
| `tools.py` | Azure DevOps data access |
| `graph.py` | LangGraph workflow |
| `model.py` | Gemini/model integration |
| `state.py` | Shared agent state |
| `wiki.py` | Azure DevOps Wiki publishing |
| `api/index.py` | FastAPI backend |
| `app/` | Next.js frontend |

---

## 🧱 Design Principles

### 1. Evidence over assumptions

The system reports what the available data supports instead of filling missing information with assumptions.

### 2. Deterministic where possible

Numerical metrics and calculations are handled by Python whenever practical.

The LLM is primarily responsible for:

- Selecting investigation paths
- Interpreting evidence
- Synthesizing findings
- Producing human-readable explanations

### 3. Adaptive investigation

The agent is not constrained to a rigid audit checklist.

The investigation path can change depending on what the agent discovers.

### 4. Safe by default

Read-only operations can execute automatically.

Operations that modify external Azure DevOps state require explicit confirmation.

---

## 🛠️ Technology Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js · React · TypeScript |
| Backend | Python · FastAPI |
| Agent Framework | LangGraph |
| LLM | Gemini |
| Data Source | Azure DevOps REST API |
| Reporting | Azure DevOps Wiki |
| Deployment | Vercel |

---

## ⚙️ Configuration

The application uses environment variables for external service configuration.

### Required Environment Variables

| Variable | Purpose |
|---|---|
| `AZURE_DEVOPS_ORG` | Azure DevOps organization |
| `AZURE_DEVOPS_PAT` | Azure DevOps authentication |
| `GOOGLE_API_KEY` | Gemini API authentication |

Example:

```env
AZURE_DEVOPS_ORG=your-organization
AZURE_DEVOPS_PAT=your-personal-access-token
GOOGLE_API_KEY=your-google-api-key
```

> **Never commit `.env`, API keys, PATs, or other credentials to Git.**

---

## 🚀 Getting Started

### Prerequisites

- Python 3.13
- Node.js
- npm
- Azure DevOps access
- Gemini API access

### 1. Clone

```bash
git clone https://github.com/Sree2622/Azure-Devops-Audit-Agent.git
cd Azure-Devops-Audit-Agent
```

### 2. Create Python Environment

```bash
python -m venv .venv
```

Windows:

```powershell
.venv\Scripts\Activate.ps1
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Frontend Dependencies

```bash
npm install
```

### 5. Configure Environment

Create your local environment file and provide the required Azure DevOps and Gemini credentials.

### 6. Start Development

```bash
npm run dev
```

Available project scripts can be inspected with:

```bash
npm run
```

---

## 🧪 Validation

Before submitting changes:

### Python compilation

```bash
python -m compileall -q .
```

### Tests

Where the project's test suite is available:

```bash
python -m pytest -q test_audit_report.py test_adaptive_audit.py
```

### Repository checks

Verify that:

- No credentials are tracked
- No generated build artifacts are committed
- Existing application behaviour remains unchanged
- Audit findings remain evidence-backed
- Documentation matches the implementation

---

## 🔐 Security

Never commit:

```text
.env
.env.local
Azure DevOps PATs
Gemini API keys
Deployment credentials
Private credentials
```

If a credential is accidentally committed:

1. Revoke or rotate it immediately.
2. Remove it from the working tree.
3. Check Git history for exposure.
4. Replace it with a new credential.
5. Review the affected service for unauthorized activity.

See [`SECURITY.md`](SECURITY.md) for the repository security policy.

---

## 🤝 Contributing

Contributions should preserve the project's evidence-first design.

Before opening a pull request:

- Keep changes focused
- Avoid unrelated refactoring
- Run relevant validation
- Do not commit secrets
- Document behavioural changes
- Preserve `OBSERVED / INFERRED / UNKNOWN` semantics

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

---

## 📌 Project Scope

This repository focuses on AI-assisted Azure DevOps auditing and reporting.

Documentation and repository-hygiene improvements should not modify application behaviour.

In particular, documentation-only changes should not alter:

- Business logic
- Audit calculations
- API behaviour
- Agent workflow
- UI behaviour
- Azure DevOps integration

unless explicitly intended.

---

## 📄 License

No open-source license is currently declared for this repository.

Until a license is added, the repository should be considered **all rights reserved**.

---

<p align="center">
  Built with Python · FastAPI · Next.js · LangGraph · Gemini · Azure DevOps
</p>
