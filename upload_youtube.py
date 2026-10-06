import json, os, re, sys, requests

CLIENT_ID = os.environ["YT_CLIENT_ID"]
CLIENT_SECRET = os.environ["YT_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["YT_REFRESH_TOKEN"]
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"
SYNTHETIC = (os.environ.get("YT_SYNTHETIC") or "true").lower() == "true"


def clean(t, limit):
    t = re.sub(r"[<>]", "", str(t)).strip()
    return t[:limit].rstrip()


def get_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN, "grant_type": "refresh_token"}, timeout=60)
    if r.status_code != 200:
        hint = ""
        if "invalid_grant" in r.text:
            hint = " (refresh token is wrong or expired: get a new one from OAuth Playground)"
        if "invalid_client" in r.text:
            hint = " (client id or client secret is wrong)"
        raise SystemExit("Google login failed %s: %s%s" % (r.status_code, r.text[:300], hint))
    return r.json()["access_token"]


def body_lines(script):
    lines = script.get("lines", [])
    if lines and lines[0].lower().startswith("psychology says"):
        lines = lines[1:]
    if script.get("cta") and lines and lines[-1] == script["cta"]:
        lines = lines[:-1]
    return lines


def fallback_meta(script):
    lines = body_lines(script)
    hook = " ".join(lines[:2]) if lines else "Psychology fact"
    title = clean(hook, 70)
    cap = script.get("caption", "")
    tags = re.findall(r"#(\w+)", script.get("hashtags", ""))
    desc = (hook + "\n\n" + cap + "\n\nFollow for daily psychology videos.\n\n"
            "#Shorts #psychology #" + (tags[0] if tags else "mindset"))
    return {"title": title, "description": desc,
            "tags": ["psychology", "psychology facts", "mindset"] + tags[:6]}


def make_meta(script):
    if script.get("yt"):
        return script["yt"]
    if not GROQ_KEY:
        return fallback_meta(script)
    lines = body_lines(script)
    prompt = (
        "Write YouTube Shorts metadata for this short psychology video.\n"
        "Topic: %s\nCategory: %s\nVideo script:\n%s\n\n"
        "Rules:\n"
        "- TITLE: at most 65 characters, put the main topic keyword near the start, make people "
        "curious, stay honest and simple, no emojis, no ALL CAPS words, no quotation marks.\n"
        "- DESCRIPTION: line 1 (under 120 characters) states the main idea with the key words "
        "people would search. Then 2 or 3 simple sentences about the idea (do not copy the script). "
        "Then the line: Follow for daily psychology videos. Then a last line with exactly 3 hashtags: "
        "#Shorts then 2 relevant hashtags.\n"
        "- TAGS: 8 to 12 search keywords separated by commas, plain English.\n"
        "- No claims of medical or scientific facts, no numbers or statistics.\n\n"
        "Reply in exactly this format and nothing else:\nTITLE:\n...\nDESCRIPTION:\n...\nTAGS:\n..."
        % (script.get("topic", ""), script.get("category", ""), "\n".join(lines)))
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": "Bearer " + GROQ_KEY, "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "temperature": 0.6, "max_completion_tokens": 1500,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=120)
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"TITLE:\s*(.*?)\s*DESCRIPTION:\s*(.*?)\s*TAGS:\s*(.*)$", txt, re.S | re.I)
        title = clean(m.group(1).replace("\n", " "), 70)
        desc = clean(m.group(2), 4000)
        tags = [t.strip() for t in m.group(3).replace("\n", ",").split(",") if t.strip()]
        if not title or not desc or not tags:
            raise ValueError("empty field")
        if "#shorts" not in desc.lower():
            desc += "\n\n#Shorts"
        return {"title": title, "description": desc, "tags": tags}
    except Exception as e:
        print("SEO generator failed, using fallback:", str(e)[:200])
        return fallback_meta(script)


def fit_tags(tags):
    out, total = [], 0
    for t in tags:
        t = clean(t, 60)
        if t and total + len(t) + 1 <= 450:
            out.append(t)
            total += len(t) + 1
    return out


def upload(video, meta, privacy, token):
    size = os.path.getsize(video)
    body = {
        "snippet": {"title": clean(meta["title"], 100), "description": clean(meta["description"], 4900),
                    "tags": fit_tags(meta["tags"]), "categoryId": "27",
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": SYNTHETIC, "embeddable": True},
    }
    r = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(size),
                 "X-Upload-Content-Type": "video/mp4"},
        data=json.dumps(body), timeout=120)
    if r.status_code != 200:
        raise SystemExit("YouTube start-upload error %s: %s" % (r.status_code, r.text[:500]))
    url = r.headers["Location"]
    with open(video, "rb") as f:
        r2 = requests.put(url, data=f, headers={"Content-Type": "video/mp4",
                                                "Content-Length": str(size)}, timeout=600)
    if r2.status_code not in (200, 201):
        raise SystemExit("YouTube upload error %s: %s" % (r2.status_code, r2.text[:500]))
    return r2.json()


def main():
    video, script_path = sys.argv[1], sys.argv[2]
    privacy = (sys.argv[3] if len(sys.argv) > 3 else os.environ.get("YT_PRIVACY") or "public").lower()
    script = json.load(open(script_path, encoding="utf-8"))
    meta = make_meta(script)
    print("TITLE:", meta["title"])
    print("DESCRIPTION:\n" + meta["description"])
    print("TAGS:", ", ".join(meta["tags"]))
    token = get_access_token()
    res = upload(video, meta, privacy, token)
    vid = res.get("id")
    st = res.get("status", {})
    print("UPLOADED video id:", vid)
    print("Asked privacy:", privacy, "| YouTube says:", st.get("privacyStatus"), "| upload:", st.get("uploadStatus"))
    print("Watch: https://www.youtube.com/shorts/%s" % vid)
    print("Studio: https://studio.youtube.com/video/%s/edit" % vid)


main()
