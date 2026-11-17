# NovaStore - Beginner Setup Guide (Windows + VS Code)

This guide assumes you are new to Python project setup. Follow the steps in
order; each one has a check so you know it worked. Time: about 15 minutes.

---

## Step 1 - Install Python 3.11 or 3.12

1. Go to <https://www.python.org/downloads/> and download Python 3.12.x.
2. Run the installer. **IMPORTANT:** on the first screen tick
   **"Add python.exe to PATH"** before clicking Install Now.
3. Verify: open PowerShell (Windows key, type "PowerShell", Enter) and run:

```powershell
python --version
```

You should see `Python 3.12.x` (or 3.11.x). If you get *"python is not
recognized"*, the PATH box was not ticked - reinstall Python.

## Step 2 - Install VS Code + extensions

1. Download VS Code from <https://code.visualstudio.com/> and install it.
2. Open VS Code -> Extensions panel (Ctrl+Shift+X) -> install:
   - **Python** (Microsoft)
   - **Pylance** (Microsoft)
   - *optional:* **Ruff** (fast linter)

## Step 3 - Open the project

1. Unzip the project zip somewhere simple, e.g. `C:\projects\novastore`
   (avoid folders with spaces in the name).
2. In VS Code: **File -> Open Folder...** -> choose `novastore`.
3. If asked "Do you trust the authors?", click yes - it is your own code.

You should see the folders `src`, `scripts`, `data`, `tests` in the Explorer.

## Step 4 - Create the virtual environment

A venv is a private Python for this project only. In VS Code open the
integrated terminal (**Terminal -> New Terminal**) and run:

```powershell
python -m venv .venv
```

Then activate it:

```powershell
.venv\Scripts\activate
```

Success check: your terminal prompt now starts with `(.venv)`.

If PowerShell blocks activation with a red "running scripts is disabled"
error, run this ONCE, then close and reopen the terminal and activate again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

## Step 5 - Tell VS Code which Python to use

Press **Ctrl+Shift+P**, type "Python: Select Interpreter", pick the one that
ends with `.venv\Scripts\python.exe`. The project ships
`.vscode/settings.json` that points there, so usually VS Code finds it
automatically.

## Step 6 - Install dependencies

In the terminal (with `(.venv)` active):

```powershell
pip install -r requirements.txt
pip install -e .
```

`-e .` installs the `novastore` package itself in editable mode, so
`import novastore` works everywhere.

Success check:

```powershell
python -c "import novastore; print('ok')"
```

## Step 7 - Create your .env with the Groq key

1. Get a (free) API key: go to <https://console.groq.com/>, create an
   account, open **API Keys**, click **Create API Key**, copy it.
2. In the project folder copy the template:

```powershell
copy .env.example .env
```

3. Open `.env` in VS Code and replace the placeholder:

```
GROQ_API_KEY=paste-your-real-key-here
```

Never commit `.env` to Git - it is already listed in `.gitignore`.

4. Optional but smart - verify your key works and see which models it can use:

```powershell
python scripts/list_models.py
```

If the default model in `.env` is ever retired by Groq, pick another id
printed by that script and set `GROQ_MODEL` in `.env`.

## Step 8 - Seed the demo database

```powershell
python scripts/seed_db.py
```

Creates `data/novastore.db` with 6 demo customers, 8 products, 10 orders,
tickets and a lead. Run again with `--force` to reset the data.

## Step 9 - Run the backend

```powershell
uvicorn novastore.api.app:app --reload --port 8000
```

Success check: open <http://127.0.0.1:8000/api/health> in your browser ->
`{"status":"ok", ...}`. Keep this terminal running.

## Step 10 - Run the chat UI (new terminal!)

Click the **+** icon in the terminal panel to open a second terminal,
activate the venv again if needed, then:

```powershell
.venv\Scripts\activate
streamlit run src/novastore/ui/chat_app.py
```

Your browser opens the chat automatically. Pick a customer in the sidebar
and try `Where is order 5482?`.

## Step 11 - Run the admin dashboard (third terminal)

```powershell
.venv\Scripts\activate
streamlit run src/novastore/ui/admin_app.py
```

Browse Overview / Conversations / Orders / Leads / Tickets / Evals.

## Step 12 - Tests and evals (optional but recommended)

```powershell
pytest
python scripts/run_evals.py
```

- `pytest` runs 42 offline tests (no API calls, uses MockLLM).
- `run_evals.py` scores the classifier on 25 cases and runs 13 scripted
  behavior scenarios; results appear in the admin Evals tab.

## Daily routine (after the first setup)

```powershell
# terminal 1
.venv\Scripts\activate
uvicorn novastore.api.app:app --reload --port 8000
# terminal 2
.venv\Scripts\activate
streamlit run src/novastore/ui/chat_app.py
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python is not recognized` | Reinstall Python with "Add to PATH" ticked |
| Activation blocked (`ps1 cannot be loaded`) | `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` (once) |
| `pip` installs but imports fail | You skipped `pip install -e .`, or the venv is not active |
| `ModuleNotFoundError: novastore` | Select the `.venv` interpreter (Step 5) |
| API 401 from Groq | Wrong/missing `GROQ_API_KEY` in `.env`; check for stray spaces |
| API 404 / model not found | Run `python scripts/list_models.py`, set `GROQ_MODEL` to a printed id |
| Streamlit says "Cannot reach the API" | The uvicorn terminal is not running (Step 9) |
| Port 8000 already in use | Another app took it: use `--port 8001` and set `UI_API_URL=http://127.0.0.1:8001` in `.env` |
| `database is locked` | Close other terminals/DB browsers using the app, then retry |
| Want to run with no key at all | Set `USE_MOCK_LLM=true` in `.env` |

## Next reading

- `README.md` - architecture and the project's rules
- `docs/whatsapp.md` - wiring the WhatsApp channel later
- The code itself: start at `src/novastore/agent/agent.py` and follow `run()`.
