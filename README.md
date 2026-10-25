# Your automatic LinkedIn poster — beginner's step-by-step guide

This system writes LinkedIn posts for you and posts them on a schedule. It picks
topics smartly (no repeats, tries to be timely), sometimes adds a photo, and
**always waits for your one-click approval** before anything goes live.

Everything runs in the cloud. Nothing installs on your computer — ever.

---

## How it actually works (plain English)

1. **GitHub Actions** = the alarm clock. Runs on GitHub's servers on your schedule.
2. **Gemini AI** = the brain. It reads your topic pool, checks what it posted
   recently (so it doesn't repeat), picks the best angle for today, and writes
   the post in your voice. Sometimes it adds a matching photo.
3. **You** = the gatekeeper. You get an email, read the draft, and tap Approve
   (or Reject to skip). Takes a few seconds.
4. **LinkedIn API** = the hand. Only after your approval, it publishes the post.

---

## The files (all editable on GitHub, no downloads)

| File | What it's for | Do you edit it? |
|---|---|---|
| `topics.txt` | Your pool of topic angles, one per line | **Yes — on GitHub** |
| `config.yaml` | Your niche, voice, image settings | **Yes — on GitHub** |
| `last_topic.txt` | Auto-created; tracks the last topic so it doesn't repeat | No |
| `post_to_linkedin.py` | The engine | No |
| `.github/workflows/post.yml` | Your schedule | Yes — to change times |
| `requirements.txt` | Dependencies | No |
| `get_token.py` | Backup tool (not needed for cloud setup) | No |

---

# PHASE A — Collect your keys (all in the browser, ~15 min)

Open a blank note to paste keys as you go. You need 2 (or 3).

## A1. LinkedIn — get your access token
1. Go to **linkedin.com/developers/apps** → Create app.
2. Link a LinkedIn Page (make a simple one first if you don't have any).
3. App → **Products** tab → request both (instant, no waiting):
   - **Share on LinkedIn**
   - **Sign In with LinkedIn using OpenID Connect**
4. App → **Auth** tab → under **OAuth 2.0 tools** → click **Create token**.
5. Tick **openid**, **profile**, and **w_member_social** → Request access token → approve.
6. Copy the token → paste it in your notes as `LINKEDIN_ACCESS_TOKEN`.

## A2. Gemini (AI) — get your API key
1. Go to **aistudio.google.com/apikey** → sign in with Google → Create API key.
2. Copy it → notes as `GEMINI_API_KEY`.

## A3. Pexels (photos) — optional but recommended
1. Go to **pexels.com/api** → sign in → Get Started.
2. Copy the key → notes as `PEXELS_API_KEY`.
3. (Skip this if you want text-only posts — set `image.enabled: false` in config later.)

---

# PHASE B — Put it on GitHub (~10 min)

## B1. Create the repo
1. Sign up free at **github.com** if you haven't.
2. Click **+** (top right) → **New repository**.
3. Name it anything (e.g. `my-linkedin-poster`).
4. **Choose PUBLIC.** (The free approval gate only works on public repos. Your keys
   stay encrypted and invisible — only harmless code is visible.)
5. Create repository.

## B2. Upload the files
1. On the empty repo page, click **"uploading an existing file"**.
2. Drag all 7 files from this chat into the browser.
   Important: keep `.github/workflows/post.yml` in its folder. If the drag
   flattens it, click **Add file → Create new file** and type the full path
   `.github/workflows/post.yml`, then paste the file's contents.
3. Commit changes.

> Nothing installs on your computer — this is a normal browser upload.

## B3. Add your keys to the secret vault
1. In the repo → **Settings → Secrets and variables → Actions**.
2. Click **New repository secret** for each (name must match exactly):
   - `LINKEDIN_ACCESS_TOKEN`
   - `GEMINI_API_KEY`
   - `PEXELS_API_KEY` (only if you did A3)
3. These are encrypted. Even you can't see them after saving. The code reads them
   automatically at run time — you never type keys into any file.

---

# PHASE C — Turn on the approval gate (~3 min)

1. Repo → **Settings → Environments → New environment**.
2. Name it exactly: `production` → Configure environment.
3. Tick **Required reviewers** → type your GitHub username → select it.
4. **Save protection rules.**

Now every post pauses and asks you before publishing.

> **To go fully automatic later:** come back, untick Required reviewers, save.

---

# PHASE D — Set your schedule (~2 min)

1. Open `.github/workflows/post.yml` in the repo → pencil icon to edit.
2. Find the `cron` lines. Times are **UTC** (Pakistan = UTC+5, subtract 5 hours):
   ```
   - cron: "0 5 * * 2"   # Tue 10:00 PKT
   - cron: "0 5 * * 4"   # Thu 10:00 PKT
   ```
   Days: 0=Sun 1=Mon 2=Tue 3=Wed 4=Thu 5=Fri 6=Sat. Add or remove lines freely.
3. Commit.

---

# PHASE E — Make the posts yours (~10 min, all on GitHub)

## E1. Your topics — `topics.txt`
Click the file → pencil → edit directly. One topic per line. These are your
**angles**, not post titles — the AI picks from this pool and writes around the
chosen angle. Examples already there; replace them with your niche. The smarter
your topics, the better every post. Commit when done.

## E2. Your niche and voice — `config.yaml`
Click → pencil → edit:
- **niche** — your field and audience in 1-2 sentences.
- **voice** — how you sound, like briefing a ghostwriter.
- **style_samples** — paste 1-2 of your real past posts. This is the single
  biggest trick for sounding like you, not a robot.
- **image → probability** — 0.5 = about half get a photo. 0 = never. 1 = always.
Commit when done.

---

# PHASE F — Test it once

1. Repo → **Actions** tab → enable workflows if asked.
2. Click **LinkedIn Auto Post** → **Run workflow** → **Run workflow**.
3. The **generate** job runs and writes the draft. Then it pauses:
   **"Review pending deployments"** appears. You also get an email.
4. Click the run → read the draft in the Summary → click **Review deployments →
   production → Approve and deploy**.
5. The **publish** job runs and posts to your LinkedIn. Check your profile.

From now on it does this automatically on your schedule.

---

## Day-to-day

**Approving a post:** you get a GitHub email with a link. Open it, read the draft,
tap Approve (or Reject to skip). A few seconds, one button.

**Changing topics:** click `topics.txt` on GitHub → pencil → edit → commit. Done.
The AI won't repeat the last topic — it tracks that automatically.

**Tweaking voice or images:** edit `config.yaml` the same way.

---

## Maintenance

- **Every ~60 days:** LinkedIn's token expires. Redo Phase A1 (browser token
  generator, 2 minutes) and paste the new value over the old secret.
- **Timing isn't exact:** scheduled runs can start up to ~30 min late. Normal.
- **If a photo fails,** the post still goes out as text — nothing breaks.
- **Going fully automatic:** Settings → Environments → production → untick
  Required reviewers → Save. Re-tick anytime to bring approval back.
