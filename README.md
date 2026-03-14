# DescVid

YouTube video & audio downloader built with **FastAPI** and **yt-dlp**, ready to deploy on [Railway](https://railway.app) or [Render](https://render.com).

## Features

- Download YouTube videos (mp4) in best / 720p / 480p quality
- Download audio only (mp3)
- Rate-limited API (15 req / min per IP)
- Protected by an `API_KEY` environment variable
- Optional YouTube bot-detection bypass via `YT_COOKIES` or `YT_OAUTH2_TOKEN`

---

## Local development

### Prerequisites

- Python 3.11+
- `ffmpeg` installed and on your `PATH`
- [GitHub CLI](https://cli.github.com/) (`gh`) if you plan to push to GitHub

### 1 — Clone & install

```bash
git clone https://github.com/Dany36E/DescVid.git
cd DescVid
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2 — Authenticate with GitHub CLI

If you need to push changes or let VS Code Copilot create/clone repos on your behalf, authenticate once:

```bash
# Interactive (opens a browser or device-flow prompt)
gh auth login

# Non-interactive (pipe a personal access token)
echo "<YOUR_PERSONAL_ACCESS_TOKEN>" | gh auth login --with-token
```

> **Tip:** create a fine-grained token with *Contents: read & write* and *Workflows: read & write* scopes at <https://github.com/settings/tokens>.

### 3 — Configure environment

Copy the example below into a `.env` file (already git-ignored):

```dotenv
API_KEY=changeme          # required — protects /api/info and /api/download
ALLOWED_ORIGIN=*          # restrict to your frontend origin in production
# YT_COOKIES=<Netscape cookie file contents>   # optional — bypasses bot detection
# YT_OAUTH2_TOKEN=<JSON token>                 # optional — alternative bypass
```

### 4 — Run the server

```bash
uvicorn main:app --reload --port 8000
```

Open <http://localhost:8000> in your browser.

---

## Deployment

### Railway

1. Connect this repository in the Railway dashboard.
2. Add the environment variables (`API_KEY`, optionally `YT_COOKIES`).
3. Railway reads `nixpacks.toml` automatically — `ffmpeg` is included.

### Render

1. Create a new **Web Service** pointing to this repo.
2. Set **Build Command**: `pip install -r requirements.txt`
3. Set **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Add environment variables in the Render dashboard.

---

## API

| Endpoint | Auth | Description |
|---|---|---|
| `GET /` | — | Serves the frontend |
| `GET /api/version` | — | Returns app version |
| `GET /api/info?url=…&key=…` | API key | Returns video metadata |
| `GET /api/download?url=…&format=mp4&quality=best&key=…` | API key | Streams the file |
| `GET /api/debug?key=…` | API key | Diagnostic info |

---

## CI

Pull requests and pushes to `main` trigger the GitHub Actions workflow (`.github/workflows/ci.yml`), which:

1. Authenticates the GitHub CLI using the built-in `GITHUB_TOKEN`:
   ```bash
   echo "$GH_TOKEN" | gh auth login --with-token
   ```
2. Installs dependencies.
3. Runs `flake8` (hard-fail on syntax errors; warn-only on style).

---

## License

MIT
