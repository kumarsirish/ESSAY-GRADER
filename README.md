# CMRIT – Essay Assessment App · Deployment Guide

## Files
```
app.py                    ← main Streamlit application (powered by Groq + Supabase)
requirements.txt          ← Python dependencies
.streamlit/secrets.toml   ← local secrets (GROQ_API_KEY, SUPABASE_URL, SUPABASE_KEY) — not committed to git
```

Student submissions and admin settings are stored in **Supabase** (Postgres), not in local files — see below.

---

## Database (Supabase)

This app stores all data in two Supabase tables instead of local JSON files, so submissions survive app restarts/redeploys on Streamlit Cloud (whose local filesystem is wiped every time the app sleeps and wakes back up).

### One-time setup
1. Create a free project at **https://supabase.com**.
2. In the project dashboard, go to **SQL Editor → New query**, paste the following, and click **Run**:

```sql
create table if not exists submissions (
  usn text primary key,
  data jsonb not null,
  updated_at timestamptz not null default now()
);

create table if not exists app_config (
  key text primary key,
  value jsonb not null
);
```

3. Go to **Project Settings → API** and copy:
   - **Project URL** → `SUPABASE_URL`
   - **anon / publishable key** → `SUPABASE_KEY`
4. Add both to your secrets (local `.streamlit/secrets.toml` or Streamlit Cloud's Secrets panel — see below).

Row Level Security is left off on these tables (the default for tables created via SQL Editor), so the publishable key has full read/write access. That's fine here because the key only ever lives server-side in Streamlit secrets — it's never sent to the browser.

### Schema notes
Each table stores its payload as a single `jsonb` column rather than one column per field:
- `submissions`: one row per USN. `data` holds the full submission record (name, topic, essay, scores, etc.) exactly as the app builds it in Python.
- `app_config`: one row, `key = 'settings'`, `value = {"copy_paste_enabled": true/false}` — toggled from the Admin Report page.

This keeps the schema stable even as the grading rubric or stored fields evolve — no migrations needed when a new field is added.

---

## Run locally

```bash
pip install -r requirements.txt
```

Create `.streamlit/secrets.toml` in the project root:
```toml
GROQ_API_KEY  = "gsk_..."
SUPABASE_URL  = "https://xxxxxxxx.supabase.co"
SUPABASE_KEY  = "sb_publishable_..."
```

(Alternatively, set `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` as environment variables instead of using secrets.toml.)

Then run:
```bash
streamlit run app.py
```

Open http://localhost:8501

> Always run with `streamlit run app.py` — running `python app.py` directly will not work (Streamlit's session/state machinery only exists inside the Streamlit runtime).

---

## Deploy on Streamlit Community Cloud (free, recommended)

### Step 1 – Push to GitHub
1. Create a **new GitHub repository** (public or private).
2. Push `app.py` and `requirements.txt` to the repo root. Do **not** commit `.streamlit/secrets.toml` (it's in `.gitignore`) — secrets are configured separately in Step 2.

### Step 2 – Connect to Streamlit Cloud
1. Go to **https://share.streamlit.io** → "New app"
2. Select your GitHub repo and branch.
3. Set **Main file path** → `app.py`
4. Click **Advanced settings → Secrets** and add:

```toml
GROQ_API_KEY  = "gsk_..."
SUPABASE_URL  = "https://xxxxxxxx.supabase.co"
SUPABASE_KEY  = "sb_publishable_..."
```

5. Click **Deploy**.

Your app will be live at:
`https://<your-app-name>.streamlit.app`

### Updating after deploy
Any push to the connected branch auto-redeploys the app. Update the Secrets panel (Step 2.4) any time a key needs to change — no redeploy needed for secrets changes. Since data now lives in Supabase rather than the app's local disk, submissions survive redeploys and sleep/wake cycles.

---

## Get your Groq API key

1. Go to **https://console.groq.com**
2. Sign up / log in → API Keys → Create API Key
3. Copy the key (starts with `gsk_`)
4. Paste into Streamlit Secrets (cloud) or `.streamlit/secrets.toml` / env var (local) as shown above

---

## Groq rate limits & quota

Groq's free tier comes with rate limits (requests/tokens per minute **and** per day) that vary by model and can change — check current numbers on your account at **https://console.groq.com/settings/limits**. Groq also offers paid **Dev Tier** / pay-as-you-go plans with substantially higher limits if the free tier isn't enough for your class size — see **https://console.groq.com/settings/billing**.

If the free daily quota is exhausted mid-test, the app catches Groq's rate-limit error and shows students a friendly message asking them to retry the next day once the quota resets, instead of a raw API error. The essay text itself is **not** persisted anywhere if grading fails, so warn students to copy their essay text somewhere safe before retrying (e.g. paste it into a personal notes app) if they hit this message.

---

## Concurrency — how many students can take the test at once?

There's no hard-coded cap in the app itself, but real-world concurrency is limited by two independent factors:

1. **Hosting resources.** Streamlit Community Cloud's free tier runs your app on a small shared instance (roughly 1 CPU / 1 GB RAM) with no auto-scaling. It comfortably handles a handful of concurrent users; a full class (30+) hitting it at the exact same moment may see slowdowns. For a full-class rollout, consider a paid Streamlit Cloud plan or self-hosting on a larger VM.
2. **Groq API rate limits.** Each essay submission makes one LLM call. If many students submit within the same minute, Groq's per-minute rate limit (not just the daily quota) can throttle or queue requests — see the Groq section above.

Data storage is no longer a concurrency bottleneck: Supabase (Postgres) handles concurrent upserts safely, unlike the old local-JSON-file approach where two simultaneous writes could clobber each other.

**Practical guidance:** for a single class section (≤30–40 students) spread across a 20-minute test window, the current setup is fine. For multiple sections running simultaneously or a large cohort submitting in a tight window, plan for a paid Streamlit hosting tier — the Supabase free tier's connection/request limits are generous enough that it's rarely the bottleneck at this scale.

---

## Admin access

Navigate to the app → select **Admin Report** → enter:
```
sirish.k@cmrit.ac.in
```

From the Admin Report page, a **"Allow copy-paste in the essay window for students"** toggle controls whether students can copy/paste/cut in the essay box. It's on by default. Toggling it updates the `app_config` row in Supabase and applies to all students within ~30 seconds (the exam page auto-refreshes every 30s).

### Admin testing mode

If you register for the test (on the home page, not the Admin Report page) using the admin email (`sirish.k@cmrit.ac.in`) in the optional Email field:
- The one-attempt-per-USN limit is bypassed, so you can repeat the test with the same USN as many times as needed.
- Copy-paste is always allowed for you regardless of the student-facing toggle.
- Your essay and grading result are **not** written to the `submissions` table and won't appear in the Admin Report or CSV export.

---

## Feature summary

| Feature | Status |
|---|---|
| Student registration (name, USN required; email optional) | ✅ |
| Data stored in Supabase (Postgres) — survives Streamlit Cloud restarts | ✅ |
| 20-minute countdown timer (colour-coded) | ✅ |
| Live word counter while typing (multiple spaces count as one word) | ✅ |
| One **attempt** per USN — marked at test start, not just on submit (bypassed for admin testing) | ✅ |
| Admin-controlled copy/paste toggle for students; always allowed for the admin test account | ✅ |
| Essay box & submit button disabled when time runs out | ✅ |
| Essay capped at 200 words before being sent to the AI grader | ✅ |
| AI grading via Groq / LLaMA 3.3 70B — 5-criteria rubric (100 pts: Content & Understanding 30, Critical Thinking & Analysis 25, Organization & Structure 20, Evidence & Examples 15, Language & Presentation 10) | ✅ |
| Friendly message on daily Groq quota exhaustion | ✅ |
| Instant feedback & score breakdown bars | ✅ |
| Admin report (email-gated) | ✅ |
| Admin test runs excluded from submissions/report/CSV | ✅ |
| Search / grade filter in report | ✅ |
| CSV export | ✅ |
