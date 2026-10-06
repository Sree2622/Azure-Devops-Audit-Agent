# Azure DevOps Audit Agent



An evidence-driven AI agent for analyzing Azure DevOps boards and sprints, identifying delivery risks, and publishing structured audit reports to Azure DevOps Wiki.



The project combines \*\*Azure DevOps REST APIs, Python, FastAPI, LangGraph, Gemini, and Next.js\*\* to provide adaptive board investigation rather than a fixed checklist-based audit.



\## Overview



The Azure DevOps Audit Agent takes a project, team, and natural-language audit request and performs an evidence-backed investigation of the selected Azure DevOps environment.



It is designed around one core principle:



> \*\*Be flexible about what to investigate, but strict about what to claim.\*\*



The agent distinguishes between:



\- \*\*OBSERVED\*\* — directly supported by Azure DevOps data

\- \*\*INFERRED\*\* — reasonable interpretation derived from observed evidence

\- \*\*UNKNOWN\*\* — information that cannot be established from available data



This prevents the system from inventing owners, deadlines, blockers, dependencies, or severity levels that are not supported by evidence.



\## Architecture



```text

┌─────────────────────┐

│      Next.js UI     │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│   FastAPI /api/\*    │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│ Azure DevOps APIs   │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│ LangGraph + Gemini  │

│ Adaptive Audit      │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│ Audit / Sprint /    │

│ Board Analysis      │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│ Azure DevOps Wiki   │

└─────────────────────┘

```



\## Key Capabilities



\- Azure DevOps project and team selection

\- Board and sprint health analysis

\- Adaptive investigation driven by the audit request

\- Aging and stalled work detection

\- Workload concentration analysis

\- Deadline pressure analysis

\- RAID-style risk analysis

\- Evidence-backed findings

\- OBSERVED / INFERRED / UNKNOWN classification

\- Deterministic calculation of numerical metrics

\- Gemini-assisted investigation and interpretation

\- Audit report generation

\- Azure DevOps Wiki publishing

\- Read-only analysis by default

\- Explicit confirmation for state-changing operations



\## Audit Flow



The investigation follows an adaptive workflow:



```text

DISCOVER

&#x20;  ↓

TRIAGE

&#x20;  ↓

INVESTIGATE

&#x20;  ↓

VALIDATE

&#x20;  ↓

ASSESS

&#x20;  ↓

REPORT

```



The agent can choose which evidence to investigate based on the request and the information discovered during the audit.



It does not rely on a rigid checklist when the available evidence suggests that another investigation path is more appropriate.



\## Evidence Model



The system separates facts from interpretation.



\### OBSERVED



A fact directly supported by Azure DevOps data.



Example:



```text

OBSERVED:

Work item #123 has remained in the Active state for 18 days.

```



\### INFERRED



An interpretation derived from observed information.



Example:



```text

INFERRED:

The work item may represent aging delivery work requiring attention.

```



\### UNKNOWN



Information that cannot be established from the available evidence.



Example:



```text

UNKNOWN:

No confirmed blocker was available from the retrieved Azure DevOps data.

```



This approach is intended to reduce unsupported conclusions and hallucinated project-management information.



\## Architecture \& Modules



```text

agent/

├── adaptive\_audit.py

├── audit.py

├── board\_review.py

├── config.py

├── graph.py

├── main.py

├── model.py

├── prompts.py

├── sprint\_health.py

├── state.py

├── tools.py

└── wiki.py



api/

└── index.py



app/

├── globals.css

├── layout.tsx

└── page.tsx

```



\### Core components



| Component | Responsibility |

|---|---|

| `adaptive\_audit.py` | Adaptive audit investigation |

| `audit.py` | Audit orchestration and reporting |

| `board\_review.py` | Board-level analysis |

| `sprint\_health.py` | Sprint health analysis |

| `tools.py` | Azure DevOps data access |

| `graph.py` | LangGraph workflow |

| `model.py` | Model integration |

| `prompts.py` | Agent instructions |

| `state.py` | Shared audit state |

| `wiki.py` | Azure DevOps Wiki publishing |

| `api/index.py` | FastAPI entry point |

| `app/` | Next.js frontend |



\## Design Principles



\### Evidence over assumptions



The system should report what the available data supports rather than filling gaps with assumptions.



\### Deterministic where possible



Numerical metrics and calculations are handled deterministically in Python whenever practical.



The model is primarily used for:



\- selecting investigation paths

\- interpreting evidence

\- synthesizing findings

\- producing human-readable explanations



\### Adaptive investigation



The audit process is not limited to a fixed set of checks.



The investigation can change depending on:



\- the user's audit request

\- discovered evidence

\- board state

\- sprint state

\- available Azure DevOps data



\### Safe mutations



Read-only operations can run automatically.



Operations that modify external state require explicit confirmation.



\## Technology Stack



\### Frontend



\- Next.js

\- React

\- TypeScript



\### Backend



\- Python

\- FastAPI



\### AI / Agent



\- LangGraph

\- Gemini

\- Tool-based investigation



\### Platform



\- Azure DevOps REST API

\- Azure DevOps Wiki

\- Vercel



\## Configuration



The application expects the required credentials and configuration to be supplied through environment variables.



Typical configuration includes:



```text

AZURE\_DEVOPS\_ORG

AZURE\_DEVOPS\_PAT

GOOGLE\_API\_KEY

```



Create a local `.env` / `.env.local` file as appropriate for your environment.



\*\*Never commit credentials, API keys, PATs, or other secrets to Git.\*\*



\## Local Development



\### Prerequisites



\- Python 3.13

\- Node.js

\- npm

\- Azure DevOps access

\- Gemini API access



\### Backend



Create and activate a Python virtual environment, then install the project's Python dependencies.



```bash

python -m venv .venv

```



Windows:



```powershell

.venv\\Scripts\\Activate.ps1

```



Install dependencies:



```bash

pip install -r requirements.txt

```



\### Frontend



Install JavaScript dependencies:



```bash

npm install

```



Run the Next.js development server:



```bash

npm run dev

```



The available project scripts can be inspected with:



```bash

npm run

```



\## Validation



Before submitting changes, validate the Python source:



```bash

python -m compileall -q .

```



Where the project's test suite is available:



```bash

python -m pytest -q test\_audit\_report.py test\_adaptive\_audit.py

```



Also verify that:



\- no secrets are present in tracked files

\- generated files are not accidentally committed

\- existing application behaviour remains unchanged

\- audit findings remain evidence-backed

\- documentation matches the current implementation



\## Security



Security-sensitive configuration should always be supplied through environment variables.



Do not commit:



\- Azure DevOps Personal Access Tokens

\- Gemini API keys

\- `.env` files

\- private credentials

\- local virtual environments

\- build output

\- deployment credentials



See \[`SECURITY.md`](SECURITY.md) for the project's security-reporting guidance.



\## Contributing



Contributions should preserve the project's evidence-first design.



Before opening a pull request:



1\. Review the existing architecture.

2\. Keep changes focused.

3\. Avoid unrelated refactoring.

4\. Run the available validation commands.

5\. Do not commit secrets or generated files.

6\. Clearly describe behavioural changes.

7\. Preserve OBSERVED / INFERRED / UNKNOWN semantics.



See \[`CONTRIBUTING.md`](CONTRIBUTING.md) for additional guidance.



\## Project Scope



This repository is intended to provide an Azure DevOps auditing and reporting system with an AI-assisted investigation layer.



Documentation and repository hygiene should not alter the application's:



\- business logic

\- audit calculations

\- API behaviour

\- agent workflow

\- UI behaviour

\- Azure DevOps integration



unless a change explicitly targets those areas.



\## License



No open-source license is currently declared for this repository.



Until a license is added, the repository should be treated as \*\*all rights reserved\*\* and should not be assumed to grant permission to reuse, modify, or redistribute the code.



\---



Built with Python, FastAPI, Next.js, LangGraph, Gemini, and Azure DevOps.# Azure DevOps Audit Agent



An evidence-driven AI agent for analyzing Azure DevOps boards and sprints, identifying delivery risks, and publishing structured audit reports to Azure DevOps Wiki.



The project combines \*\*Azure DevOps REST APIs, Python, FastAPI, LangGraph, Gemini, and Next.js\*\* to provide adaptive board investigation rather than a fixed checklist-based audit.



\## Overview



The Azure DevOps Audit Agent takes a project, team, and natural-language audit request and performs an evidence-backed investigation of the selected Azure DevOps environment.



It is designed around one core principle:



> \*\*Be flexible about what to investigate, but strict about what to claim.\*\*



The agent distinguishes between:



\- \*\*OBSERVED\*\* — directly supported by Azure DevOps data

\- \*\*INFERRED\*\* — reasonable interpretation derived from observed evidence

\- \*\*UNKNOWN\*\* — information that cannot be established from available data



This prevents the system from inventing owners, deadlines, blockers, dependencies, or severity levels that are not supported by evidence.



\## Architecture



```text

┌─────────────────────┐

│      Next.js UI     │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│   FastAPI /api/\*    │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│ Azure DevOps APIs   │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│ LangGraph + Gemini  │

│ Adaptive Audit      │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│ Audit / Sprint /    │

│ Board Analysis      │

└──────────┬──────────┘

&#x20;          │

&#x20;          ▼

┌─────────────────────┐

│ Azure DevOps Wiki   │

└─────────────────────┘

```



\## Key Capabilities



\- Azure DevOps project and team selection

\- Board and sprint health analysis

\- Adaptive investigation driven by the audit request

\- Aging and stalled work detection

\- Workload concentration analysis

\- Deadline pressure analysis

\- RAID-style risk analysis

\- Evidence-backed findings

\- OBSERVED / INFERRED / UNKNOWN classification

\- Deterministic calculation of numerical metrics

\- Gemini-assisted investigation and interpretation

\- Audit report generation

\- Azure DevOps Wiki publishing

\- Read-only analysis by default

\- Explicit confirmation for state-changing operations



\## Audit Flow



The investigation follows an adaptive workflow:



```text

DISCOVER

&#x20;  ↓

TRIAGE

&#x20;  ↓

INVESTIGATE

&#x20;  ↓

VALIDATE

&#x20;  ↓

ASSESS

&#x20;  ↓

REPORT

```



The agent can choose which evidence to investigate based on the request and the information discovered during the audit.



It does not rely on a rigid checklist when the available evidence suggests that another investigation path is more appropriate.



\## Evidence Model



The system separates facts from interpretation.



\### OBSERVED



A fact directly supported by Azure DevOps data.



Example:



```text

OBSERVED:

Work item #123 has remained in the Active state for 18 days.

```



\### INFERRED



An interpretation derived from observed information.



Example:



```text

INFERRED:

The work item may represent aging delivery work requiring attention.

```



\### UNKNOWN



Information that cannot be established from the available evidence.



Example:



```text

UNKNOWN:

No confirmed blocker was available from the retrieved Azure DevOps data.

```



This approach is intended to reduce unsupported conclusions and hallucinated project-management information.



\## Architecture \& Modules



```text

agent/

├── adaptive\_audit.py

├── audit.py

├── board\_review.py

├── config.py

├── graph.py

├── main.py

├── model.py

├── prompts.py

├── sprint\_health.py

├── state.py

├── tools.py

└── wiki.py



api/

└── index.py



app/

├── globals.css

├── layout.tsx

└── page.tsx

```



\### Core components



| Component | Responsibility |

|---|---|

| `adaptive\_audit.py` | Adaptive audit investigation |

| `audit.py` | Audit orchestration and reporting |

| `board\_review.py` | Board-level analysis |

| `sprint\_health.py` | Sprint health analysis |

| `tools.py` | Azure DevOps data access |

| `graph.py` | LangGraph workflow |

| `model.py` | Model integration |

| `prompts.py` | Agent instructions |

| `state.py` | Shared audit state |

| `wiki.py` | Azure DevOps Wiki publishing |

| `api/index.py` | FastAPI entry point |

| `app/` | Next.js frontend |



\## Design Principles



\### Evidence over assumptions



The system should report what the available data supports rather than filling gaps with assumptions.



\### Deterministic where possible



Numerical metrics and calculations are handled deterministically in Python whenever practical.



The model is primarily used for:



\- selecting investigation paths

\- interpreting evidence

\- synthesizing findings

\- producing human-readable explanations



\### Adaptive investigation



The audit process is not limited to a fixed set of checks.



The investigation can change depending on:



\- the user's audit request

\- discovered evidence

\- board state

\- sprint state

\- available Azure DevOps data



\### Safe mutations



Read-only operations can run automatically.



Operations that modify external state require explicit confirmation.



\## Technology Stack



\### Frontend



\- Next.js

\- React

\- TypeScript



\### Backend



\- Python

\- FastAPI



\### AI / Agent



\- LangGraph

\- Gemini

\- Tool-based investigation



\### Platform



\- Azure DevOps REST API

\- Azure DevOps Wiki

\- Vercel



\## Configuration



The application expects the required credentials and configuration to be supplied through environment variables.



Typical configuration includes:



```text

AZURE\_DEVOPS\_ORG

AZURE\_DEVOPS\_PAT

GOOGLE\_API\_KEY

```



Create a local `.env` / `.env.local` file as appropriate for your environment.



\*\*Never commit credentials, API keys, PATs, or other secrets to Git.\*\*



\## Local Development



\### Prerequisites



\- Python 3.13

\- Node.js

\- npm

\- Azure DevOps access

\- Gemini API access



\### Backend



Create and activate a Python virtual environment, then install the project's Python dependencies.



```bash

python -m venv .venv

```



Windows:



```powershell

.venv\\Scripts\\Activate.ps1

```



Install dependencies:



```bash

pip install -r requirements.txt

```



\### Frontend



Install JavaScript dependencies:



```bash

npm install

```



Run the Next.js development server:



```bash

npm run dev

```



The available project scripts can be inspected with:



```bash

npm run

```



\## Validation



Before submitting changes, validate the Python source:



```bash

python -m compileall -q .

```



Where the project's test suite is available:



```bash

python -m pytest -q test\_audit\_report.py test\_adaptive\_audit.py

```



Also verify that:



\- no secrets are present in tracked files

\- generated files are not accidentally committed

\- existing application behaviour remains unchanged

\- audit findings remain evidence-backed

\- documentation matches the current implementation



\## Security



Security-sensitive configuration should always be supplied through environment variables.



Do not commit:



\- Azure DevOps Personal Access Tokens

\- Gemini API keys

\- `.env` files

\- private credentials

\- local virtual environments

\- build output

\- deployment credentials



See \[`SECURITY.md`](SECURITY.md) for the project's security-reporting guidance.



\## Contributing



Contributions should preserve the project's evidence-first design.



Before opening a pull request:



1\. Review the existing architecture.

2\. Keep changes focused.

3\. Avoid unrelated refactoring.

4\. Run the available validation commands.

5\. Do not commit secrets or generated files.

6\. Clearly describe behavioural changes.

7\. Preserve OBSERVED / INFERRED / UNKNOWN semantics.



See \[`CONTRIBUTING.md`](CONTRIBUTING.md) for additional guidance.



\## Project Scope



This repository is intended to provide an Azure DevOps auditing and reporting system with an AI-assisted investigation layer.



Documentation and repository hygiene should not alter the application's:



\- business logic

\- audit calculations

\- API behaviour

\- agent workflow

\- UI behaviour

\- Azure DevOps integration



unless a change explicitly targets those areas.



\## License



No open-source license is currently declared for this repository.



Until a license is added, the repository should be treated as \*\*all rights reserved\*\* and should not be assumed to grant permission to reuse, modify, or redistribute the code.



\---



Built with Python, FastAPI, Next.js, LangGraph, Gemini, and Azure DevOps.

