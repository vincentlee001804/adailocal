## Feishu News Push Bot (Malaysia-first)

Python bot that collects Malaysia-focused news from RSS feeds, summarizes, classifies by category, and pushes interactive cards to a Feishu/Lark group via Incoming Webhook.

### Features
- Aggregates multiple Malaysian news feeds (e.g., The Star, SoyaCincau, Amanz)
- Basic classification: 科技/文娱/经济/体育/灾害/综合
- Summarization
  - Default: safe truncation
  - Optional AI: TextRank (local, free) when `USE_AI_SUMMARY=1`
- Two run modes
  - Loop mode: runs every 10 minutes
  - ONE_SHOT: run one cycle and exit (for schedulers)
- GitHub Actions workflow that runs every 10 minutes using ONE_SHOT

### Repo layout
- `adailocal.py`  Core bot (feeds, classify, summarize, Feishu webhook)
- `.github/workflows/news.yml`  Scheduler (GitHub Actions, every 10 minutes)
- `requirements.txt`  Python dependencies
- `config/.env.example`  Example environment variables
- `deploy/`  Deployment files (`Dockerfile`, `Procfile`, `fly.toml`)
- `scripts/`  Helper scripts (`fb_probe.py`)
- `docs/`  Documentation (this file, PythonAnywhere setup, etc.)
- `archive/`  Old/experimental scripts (`adaiori.py`, `adailocal_backup.py`)
- `logs/`  Runtime logs and artifacts (e.g., `sent_news.txt`)

### Requirements
- Python 3.11+
- Feishu Group Incoming Webhook URL

### Quick start (local)
```bash
pip install -r requirements.txt
set FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxx   # Windows PowerShell use $env:FEISHU_WEBHOOK_URL
set MAX_PUSH_PER_CYCLE=1
set USE_AI_SUMMARY=1   # optional TextRank summaries
python adailocal.py
```

Notes
- Loop interval is 10 minutes (edit `time.sleep(600)` in `main()` if needed).
- To send only once (useful for tests): `set ONE_SHOT=1` then run.

### GitHub Actions (free scheduler)
This repo includes `.github/workflows/news.yml` which runs every 10 minutes in ONE_SHOT mode.
1) In GitHub → Settings → Secrets and variables → Actions → New repository secret
   - `FEISHU_WEBHOOK_URL` = your webhook URL
2) Actions tab → select “Push News Every 10 Minutes” → Run workflow

The workflow installs deps, runs `python adailocal.py` with env:
- `ONE_SHOT=1`, `MAX_PUSH_PER_CYCLE=1`, `USE_AI_SUMMARY=1`

### Deployment (optional)
Files in `deploy/` can be used for various platforms:
- Render: use `deploy/Procfile` (worker) and supply `FEISHU_WEBHOOK_URL`
- Fly.io: use `deploy/fly.toml`
- Docker: build with `deploy/Dockerfile`

### Fly.io quick deploy
Prereqs: install Fly CLI and login.
```bash
curl -L https://fly.io/install.sh | sh     # Windows: https://fly.io/docs/hands-on/install-windows/
fly auth login
```

Initialize app (first time only):
```bash
# If no app yet; answers will create a Docker-based app
fly launch --no-deploy --copy-config --name your-app-name
# Or, if app already exists, ensure `deploy/fly.toml` matches your app name
```

Set secrets (required):
```bash
fly secrets set FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx
# Optional tuning
fly secrets set MAX_PUSH_PER_CYCLE=1 USE_AI_SUMMARY=1 ONE_SHOT=0
```

Deploy:
```bash
fly deploy -c deploy/fly.toml
```

Run one-shot job (optional test):
```bash
fly ssh console -C "bash -lc 'ONE_SHOT=1 python adailocal.py'"
```

### Environment variables
- `FEISHU_WEBHOOK_URL`  Required. Feishu group incoming webhook
- `USE_AI_SUMMARY=1`    Enable TextRank-based AI summary (requires `sumy`)
- `MAX_PUSH_PER_CYCLE`  Limit messages per cycle (default 1 in Actions)
- `SEND_INTERVAL_SEC`   Delay between messages inside a cycle
- `ONE_SHOT=1`          Run one cycle and exit (used by Actions)

### Troubleshooting
- "Context access might be invalid: FEISHU_WEBHOOK_URL" in Actions
  - Ensure the secret `FEISHU_WEBHOOK_URL` is set; workflow validates it early.
- "NLTK tokenizers are missing" while using AI summaries
  - We use TextRank from `sumy` and avoid heavy NLTK. If you see NLTK warnings, they can be ignored; the code falls back to a simple sentence splitter.
- Feeds show `Feed parse warning`
  - Some sources throttle/deny; the bot skips gracefully and continues.

### License
MIT







