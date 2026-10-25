#!/usr/bin/env python3
"""
LinkedIn auto-poster: AI writes, you approve, it publishes.

Two modes:
  python post_to_linkedin.py generate   -> writes a draft, does NOT post
  python post_to_linkedin.py publish    -> publishes the approved draft

Topics come from topics.txt (one per line, editable on GitHub).
Niche/voice/image settings come from config.yaml.
Smart picking: avoids the last 3 topics, varies post shape, asks the AI to
weave in something currently trending when relevant.
"""

import base64
import json
import os
import random
import sys
import time

import requests
import yaml

# ---- Secrets (GitHub repository secrets) ----
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
LINKEDIN_ACCESS_TOKEN = os.environ.get("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN = os.environ.get("LINKEDIN_PERSON_URN", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")

# ---- Endpoints (verified Oct 2026) ----
# Text models are tried IN ORDER. If one is overloaded (503) or unavailable,
# it automatically falls back to the next before giving up.
GEMINI_TEXT_MODELS = ["gemini-flash-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
LINKEDIN_POSTS_URL = "https://api.linkedin.com/rest/posts"
LINKEDIN_IMAGES_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"
LINKEDIN_USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_VERSION = "202608"
PEXELS_URL = "https://api.pexels.com/v1/search"

# Draft storage
DRAFT_DIR = "draft"
POST_FILE = os.path.join(DRAFT_DIR, "post.txt")
IMAGE_FILE = os.path.join(DRAFT_DIR, "image.bin")
META_FILE = os.path.join(DRAFT_DIR, "meta.json")

# Topics starting with this tag are leadership posts -> softer, polite tone.
LEAD_TAG = "[lead]"

# Post shapes for DATA posts (rotated so the feed never feels templated).
# All are observational / insight-based, never fabricated personal stories.
FORMATS = [
    "a clear, specific insight explained simply, with a general example (a company, a team, a BI developer)",
    "a hopeful take on how a shift in the field is creating opportunity, grounded in specifics",
    "a myth-busting post: name a common belief, then calmly explain why the reality is more encouraging",
    "a practical, useful tip the reader can apply, explained through a general example not a personal anecdote",
    "an observation about where the real value in data work is moving, stated with optimism",
    "a simple comparison of two approaches and when each one helps, no drama",
    "a short, confident explanation of why one habit or idea quietly matters more than people think",
]

# Softer shapes for LEADERSHIP posts: gentle observations, never preaching.
LEAD_FORMATS = [
    "a gentle observation about what effective, kind leadership tends to look like",
    "a small, specific observation about working well with a team, noticed not preached",
    "a calm, humble reflection on a leadership idea, kept general and warm",
    "a quiet observation about a habit good leaders tend to share",
]


# ==================== loading config ====================

def load_config(path="config.yaml"):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topics(path="topics.txt"):
    topics = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):  # skip blanks and note lines
                continue
            topics.append(line)
    return topics


LAST_TOPIC_FILE = "last_topic.txt"


def get_last_topics(n=3):
    """Return the last N posted topics so we can avoid repeating them."""
    try:
        with open(LAST_TOPIC_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
            return lines[-n:]
    except FileNotFoundError:
        return []


def save_last_topic(topic):
    """Append the chosen topic to the history file (keeps last 10 lines)."""
    existing = get_last_topics(10)
    existing.append(topic)
    with open(LAST_TOPIC_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(existing[-10:]) + "\n")


def pick_topic(topics):
    """Pick a random topic, avoiding the 3 most recently used ones."""
    recent = set(get_last_topics(3))
    available = [t for t in topics if t not in recent]
    if not available:
        available = topics
    chosen = random.choice(available)
    save_last_topic(chosen)
    return chosen


# ==================== AI text generation ====================

def gemini_text(prompt, retries=4, backoff=15):
    """Generate text. Retries transient errors, falls back across models,
    and only gives up when every model has failed."""
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"temperature": 1.05}}
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    retryable = (429, 500, 502, 503, 504)
    last_err = None

    for model in GEMINI_TEXT_MODELS:
        url = f"{GEMINI_BASE}/{model}:generateContent"
        for attempt in range(1, retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                resp.raise_for_status()
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                last_err = e
                if status in (401, 403):
                    raise  # bad API key — no other model will help
                if status in retryable and attempt < retries:
                    wait = backoff * attempt
                    print(f"{model}: {status} (try {attempt}/{retries}) — retrying in {wait}s",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"{model}: giving up ({status}) — trying next model", file=sys.stderr)
                break  # move on to the next model
            except requests.exceptions.RequestException as e:
                last_err = e  # timeout / connection drop
                if attempt < retries:
                    wait = backoff * attempt
                    print(f"{model}: network issue (try {attempt}/{retries}) — retrying in {wait}s",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"{model}: network issues — trying next model", file=sys.stderr)
                break

    raise last_err if last_err else RuntimeError("Gemini text generation failed")


def build_prompt(cfg, topic, leadership=False):
    shape = pick_format(LEAD_FORMATS if leadership else FORMATS, leadership)
    niche = (cfg.get("niche") or "").strip()
    voice = ((cfg.get("leadership_voice") if leadership else cfg.get("voice")) or "").strip()
    hook_style = (cfg.get("hook_style") or "").strip()  # optional override from config.yaml
    max_tags = int(cfg.get("max_hashtags", 2))
    length = cfg.get("target_length", "90 to 160 words")
    samples = [s.strip() for s in (cfg.get("style_samples") or []) if s and s.strip()]

    tag_rule = (f"at most {max_tags} relevant hashtag(s), or none"
                if max_tags else "no hashtags at all")

    p = ["Write ONE LinkedIn post for my personal profile.\n"]
    if niche:
        p.append(f"About me and my audience:\n{niche}\n")
    p.append(f"Topic for today: {topic}\n")
    p.append(f"Shape for this post: {shape}\n")
    if not leadership:
        p.append(
            "If something is currently trending or newly released that relates to this "
            "topic, weave it in naturally. But do not force it. If nothing trending fits, "
            "just write a great standalone post on the topic.\n"
        )
    if voice:
        p.append(f"My voice for this post:\n{voice}\n")

    # Rules shared by both tones
    common_rules = (
        "- POSITIVE AND HOPEFUL, while staying realistic. Do not dwell on fear, doom, "
        "layoffs, or negativity. If the topic touches a problem, focus on the "
        "opportunity or the constructive, encouraging angle.\n"
        "- DO NOT invent personal stories or specific events as if they happened to the "
        "author. Never write 'a client called me', 'I once fixed', 'the time I...', or any "
        "made-up anecdote. Write as observation and informed perspective. When describing "
        "a scenario, keep it general: a company, a team, a BI developer, a stakeholder.\n"
        "- BE SPECIFIC AND SUBSTANTIVE. Say something concrete. No vague, generic filler "
        "that could apply to any field or any tool.\n"
        "- CUT ANY LINE THAT ONLY RESTATES AN EARLIER POINT. Every sentence must add new "
        "information, a new example, or a new angle. Do not summarize your own post or "
        "repeat the conclusion in different words. Make each line earn its place.\n"
        "- DELIVER ON THE HOOK. Whatever specific thing the first line names or promises, "
        "the body must actually address it. Do not open a loop you never close.\n"
        "- Short. Easy to skim on a phone. Vary sentence length.\n"
        "- Simple everyday English. Write like a real person, not a brand.\n"
        "- No em dashes, no double hyphens. Normal punctuation only.\n"
        "- No buzzwords: leverage, synergy, game-changer, unlock, thrilled to, elevate, "
        "dive in, in conclusion, the truth is. No 'It's not just X, it's Y' pattern.\n"
        "- No emoji spam (one max, only if natural).\n"
        f"- Hashtags: {tag_rule}.\n"
        f"- {length}. Plain text only. No title, no markdown.\n"
    )

    if leadership:
        p.append(
            "Hard rules (non-negotiable):\n"
            "- Soft, smart, polite, warm tone. Humble and reflective. Never preachy, "
            "never motivational-speaker energy.\n"
            "- Frame it as a gentle OBSERVATION, never as advice shouted at people or "
            "commands. Avoid 'you should' and 'you need to'. Prefer 'the best leaders "
            "tend to', 'it often helps when', 'something worth noticing'.\n"
            "- Open with a gentle, specific hook, not a bold provocation. No 'Did you "
            "know', no 'In today's world'.\n"
            "- Keep any example general (a lead, a teammate, a junior), not a made-up "
            "personal story about the author.\n"
            "- End with a warm but SPECIFIC question (the one small thing they would point "
            "to), or a quiet takeaway. Avoid broad 'how do you...' questions.\n"
            + common_rules
        )
    else:
        # uses hook_style from config.yaml if present, otherwise the default rule
        hook_rule = (
            f"- Hook rule: {hook_style}\n"
            if hook_style else
            "- Open with a specific, concrete first line that stops the scroll. No "
            "'In today's world', no 'Ever wondered', no 'Did you know', no throat-clearing.\n"
        )
        p.append(
            "Hard rules (non-negotiable):\n"
            + hook_rule +
            "- Include one concrete, specific detail or example, framed generally "
            "(a company, a team, a BI developer), not as a personal anecdote.\n"
            "- End with a SPECIFIC question that asks for a concrete choice, a ranking, or "
            "the one thing they would pick (for example 'which step do you always skip?'). "
            "Never a broad 'how do you do X' that invites vague answers. No hard sales CTA.\n"
            "- Confident and informative, clearly interested in data, and encouraging.\n"
            + common_rules
        )

    if samples:
        p.append("Match the voice and rhythm of my real posts below closely:\n"
                 + "\n---\n".join(samples) + "\n")
    p.append(
        "Also suggest a simple, literal image idea that fits the post (for a stock "
        "photo search). Concrete objects or scenes, not abstract ideas.\n\n"
        "Return ONLY valid JSON, no markdown fences, with exactly these keys:\n"
        '{"post": "the full post text", "image_query": "2 to 5 words for an image"}'
    )
    return "\n".join(p)


def parse_json_loose(text):
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


# ==================== images ====================

def fetch_pexels_image(query):
    if not PEXELS_API_KEY or not query:
        if not PEXELS_API_KEY:
            print("No PEXELS_API_KEY — text-only post.", file=sys.stderr)
        return None
    try:
        r = requests.get(
            PEXELS_URL,
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": query, "per_page": 12, "orientation": "landscape"},
            timeout=30,
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
        if not photos:
            return None
        src = random.choice(photos)["src"]
        img = requests.get(src.get("large") or src.get("original"), timeout=30)
        img.raise_for_status()
        return img.content
    except Exception as e:
        print("Pexels skipped:", e, file=sys.stderr)
        return None


def generate_ai_image(prompt):
    if not prompt:
        return None
    try:
        url = f"{GEMINI_BASE}/{GEMINI_IMAGE_MODEL}:generateContent"
        r = requests.post(
            url,
            headers={"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text":
                  f"A clean, professional photo for a LinkedIn post about: {prompt}. "
                  f"No text, no words, no logos, no watermarks."}]}]},
            timeout=120,
        )
        r.raise_for_status()
        for part in r.json()["candidates"][0]["content"]["parts"]:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
        return None
    except Exception as e:
        print("AI image skipped:", e, file=sys.stderr)
        return None


def get_image(cfg, image_query):
    img_cfg = cfg.get("image") or {}
    if not img_cfg.get("enabled"):
        return None
    if random.random() > float(img_cfg.get("probability", 0.0)):
        return None
    source = str(img_cfg.get("source", "pexels")).lower()
    return generate_ai_image(image_query) if source == "ai" else fetch_pexels_image(image_query)


# ==================== LinkedIn ====================

def resolve_person_urn():
    if LINKEDIN_PERSON_URN:
        return LINKEDIN_PERSON_URN
    r = requests.get(
        LINKEDIN_USERINFO_URL,
        headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}"},
        timeout=30,
    )
    r.raise_for_status()
    return f"urn:li:person:{r.json()['sub']}"


def _li_headers():
    return {
        "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "LinkedIn-Version": LINKEDIN_VERSION,
        "X-Restli-Protocol-Version": "2.0.0",
    }


def upload_image(image_bytes, author_urn):
    init = requests.post(
        LINKEDIN_IMAGES_URL,
        headers=_li_headers(),
        json={"initializeUploadRequest": {"owner": author_urn}},
        timeout=30,
    )
    init.raise_for_status()
    value = init.json()["value"]
    put = requests.put(
        value["uploadUrl"],
        headers={"Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
                 "Content-Type": "application/octet-stream"},
        data=image_bytes,
        timeout=60,
    )
    if put.status_code not in (200, 201):
        print("Image upload failed:", put.status_code, put.text, file=sys.stderr)
        return None
    time.sleep(3)
    return value["image"]


def publish(text, author_urn, image_urn=None):
    body = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED",
                         "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if image_urn:
        body["content"] = {"media": {"id": image_urn}}
    resp = requests.post(LINKEDIN_POSTS_URL, headers=_li_headers(), json=body, timeout=30)
    if resp.status_code not in (200, 201):
        print("LinkedIn error:", resp.status_code, resp.text, file=sys.stderr)
        resp.raise_for_status()
        print("Posted. ID:", resp.headers.get("x-restli-id", "(n/a)"))


# ==================== format tracking ====================

LAST_FORMAT_FILE = "last_format.txt"

def get_last_format():
    try:
        with open(LAST_FORMAT_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

def save_last_format(fmt):
    with open(LAST_FORMAT_FILE, "w", encoding="utf-8") as f:
        f.write(fmt)

def pick_format(formats, leadership=False):
    last = get_last_format()
    available = [f for f in formats if f != last]
    if not available:
        available = formats
    chosen = random.choice(available)
    save_last_format(chosen)
    return chosen



# ==================== modes ====================

def do_generate():
    cfg = load_config()
    topics = load_topics()
    if not topics:
        sys.exit("No topics in topics.txt. Add at least one line.")

    topic = pick_topic(topics)
    leadership = topic.lower().startswith(LEAD_TAG)
    clean_topic = topic[len(LEAD_TAG):].strip() if leadership else topic
    raw = gemini_text(build_prompt(cfg, clean_topic, leadership=leadership))
    try:
        data = parse_json_loose(raw)
        post = str(data["post"]).strip()
        image_query = str(data.get("image_query", "")).strip()
    except Exception:
        post, image_query = raw.strip(), ""
    if len(post) >= 2 and post[0] in "\"'" and post[-1] in "\"'":
        post = post[1:-1].strip()

    image_bytes = get_image(cfg, image_query)

    os.makedirs(DRAFT_DIR, exist_ok=True)
    with open(POST_FILE, "w", encoding="utf-8") as f:
        f.write(post)
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump({"has_image": bool(image_bytes), "image_query": image_query,
                    "topic": clean_topic, "leadership": leadership}, f)
    if image_bytes:
        with open(IMAGE_FILE, "wb") as f:
            f.write(image_bytes)

    kind = "leadership (soft tone)" if leadership else "data"
    print("--- Draft ---")
    print(post)
    print(f"--- Topic ({kind}): {clean_topic}")
    print(f"--- Image: {(image_query if image_bytes else 'none (text-only)')}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as s:
            s.write("## Your draft LinkedIn post\n\n")
            s.write(f"**Topic picked ({kind}):** {clean_topic}\n\n")
            s.write("> " + post.replace("\n", "\n> ") + "\n\n")
            s.write(f"**Image:** {('yes — ' + image_query) if image_bytes else 'no (text-only)'}\n\n")
            s.write("**Approve the next step to publish, or Reject to skip.**\n")


def do_publish():
    if not os.path.exists(POST_FILE):
        sys.exit("No draft found. Generate step must run first.")
    with open(POST_FILE, "r", encoding="utf-8") as f:
        post = f.read()
    meta = {}
    if os.path.exists(META_FILE):
        with open(META_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)

    author_urn = resolve_person_urn()
    image_urn = None
    if meta.get("has_image") and os.path.exists(IMAGE_FILE):
        with open(IMAGE_FILE, "rb") as f:
            image_urn = upload_image(f.read(), author_urn)
    publish(post, author_urn, image_urn)


def main():
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "generate"
    if mode == "generate":
        do_generate()
    elif mode == "publish":
        do_publish()
    else:
        sys.exit("Usage: python post_to_linkedin.py [generate|publish]")


if __name__ == "__main__":
    main()
