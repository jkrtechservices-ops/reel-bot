import json, os, re, sys, glob, shutil, tempfile, zipfile, requests

# ---- settings (secrets already in your GitHub repo) ----
CLIENT_ID = os.environ.get("YT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YT_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("YT_REFRESH_TOKEN", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"
SYNTHETIC = (os.environ.get("YT_SYNTHETIC") or "true").lower() == "true"

FOLDER = "manual"
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")

DISCLAIMER = ("Disclaimer: This video is for educational and entertainment purposes only and is not "
              "professional, medical or mental health advice. All rights reserved.")


# ---------------------------------------------------------------- helpers
def clean(t, limit):
    t = re.sub(r"[<>]", "", str(t)).strip()
    return t[:limit].rstrip()


def list_items():
    """zip files and loose videos in manual/, sorted by name."""
    items = [f for f in glob.glob(os.path.join(FOLDER, "*"))
             if f.lower().endswith(".zip") or f.lower().endswith(VIDEO_EXTS)]
    items.sort(key=lambda p: os.path.basename(p).lower())
    return items


def name_hint(path):
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r"^\d+[\s._-]*", "", base)          # 001_ ya 12- hata do
    base = re.sub(r"[_\-]+", " ", base).strip()
    return base


def parse_meta_txt(text):
    """TITLE: / DESCRIPTION: / TAGS: format. Returns dict or None."""
    m = re.search(r"TITLE:\s*(.*?)\s*DESCRIPTION:\s*(.*?)\s*(?:TAGS:\s*(.*))?$", text or "", re.S | re.I)
    if not m:
        return None
    title = clean(m.group(1).replace("\n", " "), 70)
    desc = clean(m.group(2), 4000)
    tags = [t.strip().lstrip("#") for t in (m.group(3) or "").replace("\n", ",").split(",") if t.strip()]
    if not title or not desc:
        return None
    if not tags:
        tags = [w for w in re.findall(r"[a-zA-Z]{4,}", title)][:6] + ["shorts"]
    if "#shorts" not in desc.lower():
        desc += "\n\n#Shorts"
    return {"title": title, "description": desc, "tags": tags}


def transcribe(path):
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(path, language="en", condition_on_previous_text=False)
        text = " ".join(s.text.strip() for s in segs).strip()
        print("TRANSCRIPT:", text[:600])
        return text
    except Exception as e:
        print("Whisper failed:", str(e)[:200])
        return ""


def add_footer(desc):
    if "disclaimer:" in desc.lower():
        return desc
    lines = desc.rstrip().split("\n")
    tag_line = ""
    if lines and lines[-1].strip().startswith("#"):
        tag_line = lines.pop().strip()
    body = "\n".join(lines).rstrip()
    out = body + "\n\n" + DISCLAIMER
    if tag_line:
        out += "\n\n" + tag_line
    return out


def fallback_meta(hint, transcript):
    first = (transcript or hint or "Short video")
    first = re.split(r"(?<=[.!?])\s", first)[0]
    title = clean(first, 70) or "Daily short"
    desc = (clean(transcript or hint, 300) + "\n\nFollow for daily videos.\n\n#Shorts")
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", hint or transcript)][:6]
    return {"title": title, "description": desc, "tags": words + ["shorts", "daily"]}


def groq_meta(hint, source_text):
    if not GROQ_KEY:
        return fallback_meta(hint, source_text)
    prompt = (
        "Write YouTube Shorts metadata for a short video.\n"
        "What the video says (speech transcript or notes): %s\n"
        "Extra hint from the file name: %s\n\n"
        "Rules:\n"
        "- TITLE: at most 65 characters, main topic keyword near the start, make people curious, "
        "stay honest and simple, no emojis, no ALL CAPS words, no quotation marks.\n"
        "- DESCRIPTION: line 1 (under 120 characters) states the main idea with the key words people "
        "would search. Then a paragraph of 4 to 6 simple sentences (about 70 to 110 words) explaining "
        "the idea in a warm, relatable way and repeating the main keywords naturally (do not copy the "
        "transcript). Then one question line asking viewers to comment their thoughts. Then the line: "
        "Follow for daily videos. Then a last line with exactly 3 hashtags: #Shorts then 2 relevant hashtags.\n"
        "- TAGS: 8 to 12 search keywords separated by commas, plain English.\n"
        "- No claims of medical or scientific facts, no numbers or statistics.\n"
        "- If the transcript is empty, use only the file name hint.\n\n"
        "Reply in exactly this format and nothing else:\nTITLE:\n...\nDESCRIPTION:\n...\nTAGS:\n..."
        % (source_text[:3000] or "(no speech found)", hint or "(none)"))
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": "Bearer " + GROQ_KEY, "Content-Type": "application/json"},
            json={"model": GROQ_MODEL, "temperature": 0.6, "max_completion_tokens": 2500,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=120)
        r.raise_for_status()
        meta = parse_meta_txt(r.json()["choices"][0]["message"]["content"])
        if not meta:
            raise ValueError("bad format")
        return meta
    except Exception as e:
        print("SEO generator failed, using fallback:", str(e)[:200])
        return fallback_meta(hint, source_text)


def fit_tags(tags):
    out, total = [], 0
    for t in tags:
        t = clean(t, 60)
        if t and total + len(t) + 1 <= 450:
            out.append(t)
            total += len(t) + 1
    return out


def get_access_token():
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN, "grant_type": "refresh_token"}, timeout=60)
    if r.status_code != 200:
        raise SystemExit("Google login failed %s: %s" % (r.status_code, r.text[:300]))
    return r.json()["access_token"]


def upload(video, meta, privacy, token):
    size = os.path.getsize(video)
    ctype = "video/quicktime" if video.lower().endswith(".mov") else "video/mp4"
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
                 "X-Upload-Content-Type": ctype},
        data=json.dumps(body), timeout=120)
    if r.status_code != 200:
        raise SystemExit("YouTube start-upload error %s: %s" % (r.status_code, r.text[:500]))
    url = r.headers["Location"]
    with open(video, "rb") as f:
        r2 = requests.put(url, data=f, headers={"Content-Type": ctype,
                                                "Content-Length": str(size)}, timeout=900)
    if r2.status_code not in (200, 201):
        raise SystemExit("YouTube upload error %s: %s" % (r2.status_code, r2.text[:500]))
    return r2.json()


def open_item(item, tmp):
    """Returns (video_path, metadata_text) for a zip or a loose video."""
    if item.lower().endswith(".zip"):
        with zipfile.ZipFile(item) as z:
            z.extractall(tmp)
        vids, txts = [], []
        for root, _, files in os.walk(tmp):
            if "__MACOSX" in root:
                continue
            for fn in files:
                p = os.path.join(root, fn)
                if fn.startswith("."):
                    continue
                if fn.lower().endswith(VIDEO_EXTS):
                    vids.append(p)
                elif fn.lower().endswith(".txt"):
                    txts.append(p)
        if not vids:
            raise ValueError("no video inside zip")
        vids.sort(key=os.path.getsize, reverse=True)
        txt = ""
        if txts:
            txts.sort(key=lambda p: os.path.basename(p).lower())
            txt = open(txts[0], encoding="utf-8", errors="ignore").read().strip()
        return vids[0], txt
    side = os.path.splitext(item)[0] + ".txt"
    txt = open(side, encoding="utf-8", errors="ignore").read().strip() if os.path.exists(side) else ""
    return item, txt


# ---------------------------------------------------------------- main
def main():
    privacy = (sys.argv[1] if len(sys.argv) > 1 else "public").lower()
    for item in list_items():
        tmp = tempfile.mkdtemp()
        try:
            try:
                video, txt = open_item(item, tmp)
            except Exception as e:
                print("Bad item, skipping:", item, str(e)[:200])
                os.rename(item, item + ".bad")      # dobara na uthaye
                continue
            print("Using:", item, "->", os.path.basename(video))
            meta = parse_meta_txt(txt)
            if meta:
                print("Metadata taken from your txt file")
            else:
                hint = name_hint(item)
                transcript = "" if txt else transcribe(video)
                meta = groq_meta(hint, txt or transcript)
            meta["description"] = add_footer(meta["description"])
            print("TITLE:", meta["title"])
            print("DESCRIPTION:\n" + meta["description"])
            print("TAGS:", ", ".join(meta["tags"]))
            token = get_access_token()
            res = upload(video, meta, privacy, token)
            vid = res.get("id")
            st = res.get("status", {})
            print("UPLOADED video id:", vid)
            print("Asked privacy:", privacy, "| YouTube says:", st.get("privacyStatus"),
                  "| upload:", st.get("uploadStatus"))
            print("Watch: https://www.youtube.com/shorts/%s" % vid)
            for p in (item, os.path.splitext(item)[0] + ".txt"):
                if os.path.exists(p):
                    os.remove(p)
                    print("Deleted:", p)
            return
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("No manual video found.")


if __name__ == "__main__":
    main()
