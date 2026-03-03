# Projects Workspace

This repository is organized as a multi-project workspace so each project stays isolated and does not clutter the repo root.

## Directory Layout

```text
.
├── projects/
│   ├── propupkeep/
│   │   ├── app.py
│   │   ├── requirements.txt
│   │   ├── .env.example
│   │   ├── README.md
│   │   └── propupkeep/
│   └── loganomdetector/
│       └── loganomdetector.py
└── .gitignore
```

## Projects

- `projects/propupkeep`: AI-powered property operations reporting MVP (Streamlit + AI formatter + routing + local persistence)
- `projects/loganomdetector`: simple log anomaly detector script

## Run PropUpkeep

```bash
cd projects/propupkeep
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```
