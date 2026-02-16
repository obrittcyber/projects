# PropUpkeep MVP

Mobile-first Streamlit MVP for AI-powered property operations reporting.

This refactor moves the prototype into a modular architecture designed for internal demos now and SaaS evolution later (multi-property, multi-tenant, stronger controls).

## Features

- Streamlit UI with three tabs:
  - **Quick Snap** (photo upload + optional note -> structured IssueReport)
  - **Unit Notes** (raw text notes -> AI structured issue report)
  - **Community Feed** (review saved activity logs + photo thumbnails)
- Pydantic domain model (`IssueReport`) and strict AI response validation
- One automatic repair retry when AI output is invalid JSON/schema
- Rules-based routing (`category + urgency -> recipients`)
- Local persistence via JSONL (no external database required)
- Environment-driven configuration via `python-dotenv`
- Structured JSON logging + user-friendly error handling
- Fact-fidelity safeguards:
  - preserve user-stated entities (unit IDs, locations, numbers, nouns)
  - extracted entity buckets + confidence fields
  - follow-up question generation when details are missing
- Uploaded images are persisted locally and referenced by IssueReport `image_path`
- Basic security hygiene:
  - Never logs API keys
  - Input sanitization for notes and filenames
  - Upload size limit enforcement
  - UI disclaimer: **Not for emergencies; call 911/management**

---

## Project Structure

```text
.
├── app.py
├── propupkeep/
│   ├── ai/
│   │   ├── formatter.py
│   │   └── prompts.py
│   ├── config/
│   │   └── settings.py
│   ├── core/
│   │   ├── errors.py
│   │   ├── logging_utils.py
│   │   ├── sanitize.py
│   │   └── workflows.py
│   ├── data/
│   ├── models/
│   │   └── issue.py
│   ├── services/
│   │   └── router.py
│   ├── storage/
│   │   └── repository.py
│   └── ui/
│       └── streamlit_app.py
└── requirements.txt
```

---

## Setup

From repo root:

```bash
cd projects/propupkeep
```

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` file in this project root (`projects/propupkeep`):

```bash
OPENAI_API_KEY=your_key_here
MODEL=gpt-4.1-mini
LOG_LEVEL=INFO
MAX_UPLOAD_MB=5
MAX_INPUT_CHARS=3000
DATA_FILE=propupkeep/data/activity.jsonl
UPLOADS_DIR=propupkeep/data/uploads
OPENAI_TIMEOUT_SECONDS=45
```

---

## Run

```bash
streamlit run app.py
```

Equivalent:

```bash
python -m streamlit run app.py
```

You can also run from repo root:

```bash
streamlit run projects/propupkeep/app.py
```

---

## Architecture (ASCII)

```text
               +-------------------------+
               | Streamlit UI (propupkeep/ui) |
               |  app.py -> streamlit    |
               +------------+------------+
                            |
                            v
               +-------------------------+
               | Core Workflow Service   |
               | (propupkeep/core/workflows) |
               +-----+-------------+-----+
                     |             |
                     |             |
                     v             v
         +----------------+   +-------------------+
         | AI Formatter   |   | Routing Service   |
         | (propupkeep/ai)|   |(propupkeep/services)|
         +-------+--------+   +---------+---------+
                 |                      |
                 v                      |
       +----------------------+         |
       | OpenAI Chat API      |         |
       +----------------------+         |
                                        v
                           +-------------------------+
                           | Persistence Repository  |
                           | JSONL (propupkeep/storage) |
                           +-------------------------+
```

---

## Core Flow

1. User selects property/building/unit/area and submits from Unit Notes or Quick Snap.
2. Notes/photo metadata are sanitized and sent to one shared issue workflow.
3. AI response must be valid JSON and pass Pydantic validation.
4. If invalid, app triggers one repair pass and retries validation once.
5. Router maps category/urgency to recipients.
6. Final IssueReport is persisted locally in JSONL and shown in UI/community feed.

---

## Future Roadmap

- Add voice transcript ingestion and image analysis pipeline
- Move JSONL repository to SQLite/Postgres with migrations
- Add authn/authz + tenant scoping for multi-property SaaS
- Add audit logs, PII tagging, and retention policies
- Add external integrations (work order systems, vendor APIs, Slack/email)
- Add monitoring, tracing, and queue-based async processing
- Expand automated tests (unit/integration/e2e)
