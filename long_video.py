#!/usr/bin/env python3
"""Long motivation videos: built a little every day, uploaded when finished.

Your script (long_scripts/*.txt) is the plan. Every run: voice (Fish)
+ stock visuals (Pixabay) + captions + SFX for the next few scenes, saved in
state/. When every scene is done: join, add music, upload to YouTube.
"""
import os, sys, re, json, math, glob, random, shutil, subprocess, difflib, base64, time
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1280, 720, 24
STATE, WORK = "state", "work"
ACCENT = (255, 214, 64)
CAP_Y = 0.80
SEG_SECONDS = 2.6            # a new visual about every 2.6 seconds
MUSIC_VOL = float(os.environ.get("LONG_MUSIC_VOL") or 0.14)
SFX_VOL = 0.55

PX_KEY = os.environ.get("PIXABAY_API_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"


# ---------------------------------------------------------------- helpers
def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError("command failed: %s\n%s" % (" ".join(cmd[:6]), p.stderr[-1500:]))
    return p.stdout


def probe_dur(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "default=nw=1:nk=1", path])
    return float(out.strip())


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def find_font():
    for p in sorted(glob.glob("fonts/*.ttf") + glob.glob("fonts/*.otf")):
        return p
    for name in ["Montserrat-ExtraBold", "Montserrat-Bold", "Poppins-ExtraBold",
                 "Poppins-Bold", "Oswald-Bold"]:
        hits = glob.glob("/usr/share/fonts/**/" + name + ".*", recursive=True)
        if hits:
            return hits[0]
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


FONT = find_font()


# ---------------------------------------------------------------- Groq
def groq(prompt, max_tokens=4000, temperature=0.8):
    if not GROQ_KEY:
        raise SystemExit("GROQ_API_KEY secret is missing")
    body = {"model": GROQ_MODEL, "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    if "gpt-oss" in GROQ_MODEL:
        body["reasoning_effort"] = "low"
    for _ in range(5):
        r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                          headers={"Authorization": "Bearer " + GROQ_KEY,
                                   "Content-Type": "application/json"},
                          json=body, timeout=180)
        if r.status_code == 429 or r.status_code >= 500:
            m = re.search(r"try again in ([\d.]+)s", r.text)
            wait = min(65, float(m.group(1)) + 2) if m else 20
            print("Groq busy, waiting %.0fs" % wait)
            time.sleep(wait)
            continue
        if r.status_code != 200:
            raise SystemExit("Groq error %s: %s" % (r.status_code, r.text[:300]))
        return r.json()["choices"][0]["message"]["content"]
    raise SystemExit("Groq kept failing, try again later")


def groq_json(prompt, max_tokens=4000):
    last = ""
    for _ in range(3):
        txt = groq(prompt, max_tokens)
        a, b = txt.find("{"), txt.rfind("}")
        try:
            return json.loads(txt[a:b + 1])
        except Exception as e:
            last = str(e)
            print("Groq JSON parse failed, retrying:", last[:100])
    raise SystemExit("Groq did not return valid JSON: " + last)


# ---------------------------------------------------------------- script file
GENERIC_KW = ["city night", "man walking", "mountain sunrise", "gym workout", "ocean waves",
              "road driving", "desk laptop", "forest path", "crowd people", "clouds sky"]


def clean_kw(lst):
    out = [re.sub(r"[^a-zA-Z ]", "", str(k)).strip().lower() for k in lst]
    return [k for k in out if k][:3]


def split_text(text, maxw=24):
    """One line of the script = one scene. Very long lines are cut at sentence ends."""
    if len(text.split()) <= maxw:
        return [text]
    sents = re.split(r"(?<=[.!?])\s+", text)
    pieces, cur = [], ""
    for sn in sents:
        if cur and len((cur + " " + sn).split()) > maxw:
            pieces.append(cur)
            cur = sn
        else:
            cur = (cur + " " + sn).strip()
    if cur:
        pieces.append(cur)
    return pieces


def parse_script(path):
    meta, scenes, headings = {}, [], []
    for raw in open(path, encoding="utf-8").read().splitlines():
        line = raw.strip().replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
        line = line.replace("*", "")
        if not line or line.startswith("//"):
            continue
        m = re.match(r"^(TITLE|DESCRIPTION|TAGS|HASHTAGS)\s*:\s*(.*)$", line, re.I)
        if m:
            meta[m.group(1).lower()] = m.group(2).strip()
            continue
        if line.startswith("##"):
            headings.append(line.lstrip("#").strip() or "Part %d" % (len(headings) + 1))
            continue
        if not headings:
            headings.append("Intro")
        parts = [p.strip() for p in line.split("|")]
        text = re.sub(r"\s+", " ", parts[0]).strip()
        if not text:
            continue
        kws = clean_kw(parts[1].split(",")) if len(parts) > 1 and parts[1] else []
        big = re.sub(r"[^A-Za-z0-9 '!?]", "", parts[2]).strip().upper() if len(parts) > 2 else ""
        if len(big.split()) > 5:
            big = ""
        sfx = parts[3].strip().lower() if len(parts) > 3 else ""
        for n, piece in enumerate(split_text(text)):
            scenes.append({"text": piece, "keywords": list(kws), "big": big if n == 0 else "",
                           "sfx": sfx if n == 0 else "", "sec": len(headings) - 1})
    if len(scenes) < 3:
        raise SystemExit("Script %s has fewer than 3 lines" % path)
    return meta, scenes, headings


def fill_keywords(scenes):
    need = [i for i, sc in enumerate(scenes) if not sc["keywords"]]
    if not need:
        return
    if GROQ_KEY:
        try:
            for b in range(0, len(need), 25):
                chunk = need[b:b + 25]
                lines = "\n".join("%d. %s" % (k + 1, scenes[i]["text"]) for k, i in enumerate(chunk))
                data = groq_json(
                    "For each numbered narration line, give 2 or 3 stock-footage search terms (each 1 or 2 "
                    "English words, concrete things a camera can film such as \"man running\", \"city night\", "
                    "\"rain window\"; never abstract words like success or motivation). Do not change the lines.\n"
                    "%s\nReply with JSON only: {\"keywords\": [[\"..\", \"..\"]]} with exactly %d lists, in the "
                    "same order." % (lines, len(chunk)), 3000)
                for k, i in enumerate(chunk):
                    if k < len(data["keywords"]):
                        scenes[i]["keywords"] = clean_kw(data["keywords"][k])
        except (Exception, SystemExit) as e:
            print("Keyword helper failed, using generic visuals:", str(e)[:150])
    for k, i in enumerate(need):
        if not scenes[i]["keywords"]:
            scenes[i]["keywords"] = [GENERIC_KW[k % len(GENERIC_KW)], GENERIC_KW[(k + 3) % len(GENERIC_KW)]]


def build_meta(user, scenes, headings, stem):
    title = re.sub(r"[<>]", "", user.get("title", "")).strip()
    desc = user.get("description", "").strip()
    tags = [t.strip() for t in user.get("tags", "").split(",") if t.strip()]
    hashtags = re.findall(r"#\w+", user.get("hashtags", ""))
    if GROQ_KEY and not (title and desc and tags):
        try:
            text = " ".join(sc["text"] for sc in scenes)[:3500]
            g = groq_json(
                "Write YouTube metadata for a motivational video with this voice-over script:\n%s\n"
                "Reply with JSON only: {\"title\": \"max 65 characters, curiosity-driven, no emojis, no ALL CAPS "
                "words\", \"description\": \"3 to 5 simple sentences (60 to 90 words) using the main keywords "
                "naturally, ending with a question asking viewers to comment\", \"tags\": [8 to 12 plain English "
                "search keywords], \"hashtags\": [\"#a\", \"#b\", \"#c\"]}" % text, 1500)
            title = title or str(g.get("title", "")).strip()
            desc = desc or str(g.get("description", "")).strip()
            tags = tags or [str(x) for x in g.get("tags", [])]
            hashtags = hashtags or [str(x) for x in g.get("hashtags", [])]
        except (Exception, SystemExit) as e:
            print("Metadata helper failed, using simple defaults:", str(e)[:150])
    title = (title or stem.replace("_", " ").title())[:70]
    desc = desc or (title + ". Watch till the end and tell us in the comments what you will start today.")
    return {"title": title, "description": desc, "tags": tags or ["motivation", "self improvement"],
            "hashtags": hashtags}


def plan_video():
    files = sorted(glob.glob("long_scripts/*.txt"))
    if not files:
        raise SystemExit("No script found. Add a .txt file in the long_scripts folder first.")
    path = files[0]
    print("Using script:", path)
    user, scenes, headings = parse_script(path)
    fill_keywords(scenes)
    stem = os.path.splitext(os.path.basename(path))[0]
    meta = build_meta(user, scenes, headings, stem)
    vid = time.strftime("v%Y%m%d%H%M%S")
    plan = {"vid": vid, "topic": meta["title"], "title": meta["title"], "headings": headings,
            "scenes": scenes, "meta": meta, "script_file": path.replace("\\", "/")}
    vdir = os.path.join(STATE, vid)
    os.makedirs(os.path.join(vdir, "parts"), exist_ok=True)
    save_json(os.path.join(vdir, "plan.json"), plan)
    save_json(os.path.join(STATE, "current.json"), {"vid": vid})
    print("Plan saved: %d scenes, %d sections, title: %s" % (len(scenes), len(headings), meta["title"]))
    return plan


# ---------------------------------------------------------------- voice
def norm(w):
    return re.sub(r"[^a-z0-9]", "", w.lower())


def word_starts(words_txt, heard, total):
    heard = [(norm(t), s, e) for t, s, e in heard if norm(t)]
    a = [norm(w) for w in words_txt]
    b = [h[0] for h in heard]
    st = [None] * len(a)
    en = [None] * len(a)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    matched = 0
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            st[blk.a + k] = heard[blk.b + k][1]
            en[blk.a + k] = heard[blk.b + k][2]
            matched += 1
    i, n = 0, len(a)
    while i < n:
        if st[i] is not None:
            i += 1
            continue
        j = i
        while j < n and st[j] is None:
            j += 1
        t0 = en[i - 1] if i > 0 else 0.0
        t1 = st[j] if j < n else total
        w = [max(len(words_txt[k]), 1) for k in range(i, j)]
        acc = 0
        for k in range(i, j):
            st[k] = t0 + (t1 - t0) * acc / sum(w)
            acc += w[k - i]
            en[k] = t0 + (t1 - t0) * acc / sum(w)
        i = j
    return st, matched


def tts_fish(text, out_wav):
    key = os.environ["FISH_API_KEY"]
    voice_id = os.environ["FISH_VOICE_ID"]
    model = os.environ.get("FISH_MODEL") or "s2.1-pro-free"
    r = None
    for attempt in range(3):
        r = requests.post(
            "https://api.fish.audio/v1/tts/stream/with-timestamp",
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json", "model": model},
            json={"text": text, "reference_id": voice_id,
                  "format": "mp3", "latency": "normal"},
            stream=True, timeout=300)
        if r.status_code == 200:
            break
        print("Fish API error %s: %s" % (r.status_code, r.text[:200]))
        time.sleep(10)
    if r is None or r.status_code != 200:
        raise SystemExit("Fish API failed (credits finished or key wrong?)")
    r.encoding = "utf-8"
    audio, align = [], {}
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except Exception:
            continue
        if ev.get("audio_base64"):
            audio.append(base64.b64decode(ev["audio_base64"]))
        if ev.get("alignment"):
            align[ev["chunk_seq"]] = (ev["chunk_audio_offset_sec"],
                                      ev["alignment"]["segments"])
    raw = os.path.join(WORK, "voice_raw.mp3")
    with open(raw, "wb") as f:
        f.write(b"".join(audio))
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, "-ar", "44100", "-ac", "2", out_wav])
    heard = []
    for seq in sorted(align):
        off, segs = align[seq]
        for s in segs:
            heard.append((s["text"], s["start"] + off, s["end"] + off))
    return heard


# ---------------------------------------------------------------- stock footage
PX_CACHE = {}


def px_get(url, params):
    for _ in range(4):
        try:
            r = requests.get(url, params=params, timeout=60)
        except Exception as e:
            print("Pixabay network error:", str(e)[:100])
            time.sleep(5)
            continue
        if r.status_code == 429:
            print("Pixabay rate limit, waiting 30s")
            time.sleep(30)
            continue
        if r.status_code != 200:
            print("Pixabay error %s: %s" % (r.status_code, r.text[:120]))
            return None
        time.sleep(0.8)
        return r.json()
    return None


def px_search(kind, q):
    """kind = video or image. Returns list of hits (may be empty)."""
    words = q.split()
    tries = [(q, 1280)]
    if len(words) > 1:
        tries.append((" ".join(words[:2]), 1280))
        tries.append((words[0], 0))
    for qq, minw in tries:
        key = (kind, qq, minw)
        if key in PX_CACHE:
            hits = PX_CACHE[key]
        else:
            params = {"key": PX_KEY, "q": qq, "per_page": 20, "safesearch": "true"}
            if minw:
                params["min_width"] = minw
            if kind == "video":
                data = px_get("https://pixabay.com/api/videos/", params)
            else:
                params.update({"image_type": "photo", "orientation": "horizontal"})
                data = px_get("https://pixabay.com/api/", params)
            hits = (data or {}).get("hits", [])
            PX_CACHE[key] = hits
        if hits:
            return hits
    return []


def download(url, path):
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(3):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                if r.status_code != 200:
                    time.sleep(3)
                    continue
                with open(path + ".part", "wb") as f:
                    for chunk in r.iter_content(1 << 16):
                        f.write(chunk)
            os.replace(path + ".part", path)
            return path
        except Exception as e:
            print("Download failed:", str(e)[:100])
            time.sleep(3)
    return None


def fallback_visual(rng):
    files = [f for e in ("png", "jpg", "jpeg") for f in glob.glob("backgrounds/*/*." + e)]
    if not files:
        raise SystemExit("No stock result and no backgrounds/ images to fall back on")
    return {"kind": "image", "path": rng.choice(sorted(files)), "id": "local"}


def get_visual(kw, seg_d, rng, used):
    if not PX_KEY:
        return fallback_visual(rng)
    order = ["video", "image"] if rng.random() < 0.75 else ["image", "video"]
    for kind in order:
        hits = px_search(kind, kw)
        fresh = [h for h in hits if "%s%s" % (kind[0], h["id"]) not in used]
        pool = (fresh or hits)[:10]
        if not pool:
            continue
        for h in rng.sample(pool, len(pool)):
            uid = "%s%s" % (kind[0], h["id"])
            if kind == "video":
                url = ""
                for size in ("medium", "small", "large", "tiny"):
                    url = (h.get("videos", {}).get(size) or {}).get("url", "")
                    if url:
                        break
                if not url:
                    continue
                path = download(url, os.path.join(WORK, "clips", uid + ".mp4"))
                if not path:
                    continue
                try:
                    dur = probe_dur(path)
                except Exception:
                    continue
                used.add(uid)
                return {"kind": "video", "path": path, "dur": dur, "id": uid}
            else:
                url = h.get("largeImageURL") or h.get("webformatURL")
                if not url:
                    continue
                path = download(url, os.path.join(WORK, "clips", uid + ".jpg"))
                if not path:
                    continue
                used.add(uid)
                return {"kind": "image", "path": path, "id": uid}
    print("No stock for %r, using local background" % kw)
    return fallback_visual(rng)


# ---------------------------------------------------------------- pictures (captions etc.)
def text_img(text, accent, size, max_w):
    font = ImageFont.truetype(FONT, size)
    words = text.upper().split()
    meas = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    space = meas.textlength(" ", font=font)
    lines, cur, cur_w = [], [], 0
    for w in words:
        ww = meas.textlength(w, font=font)
        add = ww if not cur else space + ww
        if cur and cur_w + add > max_w:
            lines.append(cur)
            cur, cur_w = [w], ww
        else:
            cur.append(w)
            cur_w += add
    if cur:
        lines.append(cur)
    key = max(range(len(words)), key=lambda i: len(re.sub(r"[^A-Za-z0-9]", "", words[i])))
    lh, pad = int(size * 1.25), 30
    layer = Image.new("RGBA", (W, lh * len(lines) + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    gi = 0
    for li, ln in enumerate(lines):
        lw = sum(meas.textlength(w, font=font) for w in ln) + space * (len(ln) - 1)
        x, y = (W - lw) / 2, pad + li * lh
        for w in ln:
            col = accent if gi == key else (255, 255, 255)
            d.text((x, y), w, font=font, fill=col, stroke_width=max(4, size // 14),
                   stroke_fill=(0, 0, 0))
            x += meas.textlength(w, font=font) + space
            gi += 1
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", layer.size, (0, 0, 0, 190)), (0, 8), layer.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(8))
    return Image.alpha_composite(shadow, layer)


def frame_png(layer, cy, path):
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    canvas.alpha_composite(layer, (0, int(cy - layer.height / 2)))
    canvas.save(path, compress_level=1)


def tag_png(label, path):
    font = ImageFont.truetype(FONT, 30)
    meas = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = meas.textlength(label, font=font)
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    x, y, pad = 40, 34, 18
    d.rounded_rectangle((x, y, x + tw + 2 * pad + 16, y + 62), radius=10, fill=(0, 0, 0, 150))
    d.rectangle((x, y, x + 8, y + 62), fill=ACCENT)
    d.text((x + pad + 12, y + 12), label, font=font, fill=(255, 255, 255))
    canvas.save(path, compress_level=1)


def gradient_png(path):
    g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    start = int(H * 0.52)
    for y in range(start, H):
        a = int(185 * ((y - start) / (H - start)) ** 1.4)
        d.line([(0, y), (W, y)], fill=(0, 0, 0, a))
    g.save(path, compress_level=1)


def caption_chunks(words, maxw=3):
    out, cur, first = [], [], 0
    for k, w in enumerate(words):
        if not cur:
            first = k
        cur.append(w)
        if len(cur) >= maxw or re.search(r"[,.!?;:]$", w) or k == len(words) - 1:
            out.append((" ".join(cur), first))
            cur = []
    return out


# ---------------------------------------------------------------- sfx
CUT_TAGS = ("woosh", "whoosh", "swoosh", "swish")
HIT_TAGS = ("riser", "buildup", "impact", "boom", "hit", "thud")
SFX_RULES = [
    (("cashregister",), {"money", "rich", "wealth", "pay", "paid", "earn", "income", "price", "cost",
                         "buy", "profit", "dollar", "dollars", "cash", "salary"}),
    (("typewriter", "keyboard"), {"write", "wrote", "type", "typing", "work", "working", "code",
                                  "study", "studying", "email", "plan", "planning"}),
    (("click",), {"click", "tap", "scroll", "scrolling", "phone", "screen", "app", "search", "online", "post"}),
    (("camera",), {"picture", "photo", "moment", "memory", "memories", "remember", "capture", "frame"}),
    (("rip",), {"break", "broke", "tear", "rip", "quit", "cut", "end", "burn", "leave", "destroy",
                "old", "past", "delete", "gone"}),
    (("turn",), {"page", "chapter", "turn", "new", "begin", "again", "next"}),
    (("decode",), {"mind", "brain", "think", "thought", "thoughts", "secret", "truth", "understand",
                   "unlock", "figure", "realize", "learn"}),
]


def sfx_files():
    return sorted(f for e in ("mp3", "wav", "ogg", "m4a", "aac", "flac") for f in glob.glob("sfx/*." + e))


def sfx_pool(files, tags):
    return [f for f in files if any(t in os.path.basename(f).lower() for t in tags)]


def is_hit(path):
    return any(t in os.path.basename(path).lower() for t in HIT_TAGS)


def choose_sfx(sc, rng, first_of_section):
    files = sfx_files()
    if not files:
        return None
    want = (sc.get("sfx") or "").strip().lower()
    if want == "none":
        return None
    if want:
        hit = sfx_pool(files, (want,))
        if hit:
            return rng.choice(hit)
    words = set(re.findall(r"[a-z']+", sc["text"].lower()))
    if sc.get("big") or first_of_section:
        pool = sfx_pool(files, HIT_TAGS)
        if pool:
            return rng.choice(pool)
    if rng.random() < 0.6:
        for tags, kw in SFX_RULES:
            if words & kw:
                pool = sfx_pool(files, tags)
                if pool:
                    return rng.choice(pool)
    if rng.random() < 0.5:
        pool = sfx_pool(files, CUT_TAGS)
        if pool:
            return rng.choice(pool)
    return None


# ---------------------------------------------------------------- scene render
def make_audio(voice, s, d, sfx, out):
    sfx_len = 2.4 if (sfx and is_hit(sfx)) else 1.4
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", "%.3f" % s, "-t", "%.3f" % (d + 0.5), "-i", voice]
    if sfx:
        sl = min(sfx_len, d)
        cmd += ["-i", sfx, "-filter_complex",
                "[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo,apad[v];"
                "[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                "atrim=0:%.2f,asetpts=PTS-STARTPTS,afade=t=out:st=%.2f:d=0.25,volume=%.2f[s];"
                "[v][s]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[a]"
                % (sl, max(0.0, sl - 0.25), SFX_VOL), "-map", "[a]"]
    else:
        cmd += ["-af", "apad"]
    cmd += ["-t", "%.4f" % d, "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", out]
    run(cmd)


GRADE = "eq=contrast=1.06:saturation=1.1:brightness=-0.04"


def render_video(plan_scene, d_frames, word_rel, tag_label, vis_list, tmp_dir, rng, out):
    d = d_frames / FPS
    n_seg = len(vis_list)
    base = d_frames // n_seg
    frames = [base] * n_seg
    frames[-1] += d_frames - base * n_seg

    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    filt = []
    for j, (vis, fr) in enumerate(zip(vis_list, frames)):
        sd = fr / FPS
        if vis["kind"] == "video":
            if vis["dur"] >= sd + 0.3:
                t0 = rng.uniform(0, vis["dur"] - sd - 0.2)
                cmd += ["-ss", "%.2f" % t0, "-t", "%.2f" % (sd + 0.5), "-i", vis["path"]]
            else:
                cmd += ["-stream_loop", "-1", "-t", "%.2f" % (sd + 0.5), "-i", vis["path"]]
            punch = int(FPS * 0.3)
            filt.append(
                "[%d:v]fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,"
                "trim=end_frame=%d,setpts=PTS-STARTPTS,"
                "zoompan=z='1.07-0.07*min(on/%d,1)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=%dx%d:fps=%d,"
                "%s,setsar=1,format=yuv420p[s%d]"
                % (j, FPS, W, H, W, H, fr, punch, W, H, FPS, GRADE, j))
        else:
            cmd += ["-i", vis["path"]]
            z = ("1+0.10*on/%d" % fr) if rng.random() < 0.5 else ("1.10-0.10*on/%d" % fr)
            filt.append(
                "[%d:v]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,setsar=1,"
                "zoompan=z='%s':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=%d:s=%dx%d:fps=%d,"
                "%s,setsar=1,format=yuv420p[s%d]"
                % (j, 2 * W, 2 * H, 2 * W, 2 * H, z, fr, W, H, FPS, GRADE, j))
    if n_seg == 1:
        filt.append("[s0]null[base]")
    else:
        filt.append("%sconcat=n=%d:v=1:a=0[base]" % ("".join("[s%d]" % j for j in range(n_seg)), n_seg))

    # overlay pictures: (png path, start, end)
    overlays = []
    grad = os.path.join(WORK, "grad.png")
    words = plan_scene["text"].split()
    chunks = caption_chunks(words)
    starts = []
    for k, (txt, fi) in enumerate(chunks):
        st = max(0.0, word_rel[fi] - 0.04)
        if starts:
            st = max(st, starts[-1] + 0.12)
        starts.append(st)
    for k, (txt, fi) in enumerate(chunks):
        st = starts[k]
        en = starts[k + 1] if k + 1 < len(chunks) else d
        if st >= d - 0.05:
            continue
        p = os.path.join(tmp_dir, "cap%d.png" % k)
        frame_png(text_img(txt, ACCENT, 60, 1100), H * CAP_Y, p)
        overlays.append((p, st, en))
    big_end = 0.0
    if plan_scene.get("big"):
        p = os.path.join(tmp_dir, "big.png")
        frame_png(text_img(plan_scene["big"], ACCENT, 112, 1150), H * 0.40, p)
        big_end = min(d, 2.9)
        overlays.append((p, 0.1, big_end))
    if tag_label:
        p = os.path.join(tmp_dir, "tag.png")
        tag_png(tag_label, p)
        overlays.append((p, 0.0, min(d, 2.6)))

    gi = n_seg
    cmd += ["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % d, "-i", grad]
    for p, a, b in overlays:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % d, "-i", p]
    dim = "drawbox=x=0:y=0:w=iw:h=ih:color=black@0.20:t=fill"
    if big_end:
        dim += ",drawbox=x=0:y=0:w=iw:h=ih:color=black@0.35:t=fill:enable='between(t,0.05,%.2f)'" % big_end
    filt.append("[base]%s[b0]" % dim)
    filt.append("[b0][%d:v]overlay=0:0[b1]" % gi)
    cur = "b1"
    for k, (p, a, b) in enumerate(overlays):
        nxt = "o%d" % k
        filt.append("[%s][%d:v]overlay=0:0:enable='between(t,%.3f,%.3f)'[%s]" % (cur, gi + 1 + k, a, b, nxt))
        cur = nxt
    cmd += ["-filter_complex", ";".join(filt), "-map", "[%s]" % cur, "-frames:v", str(d_frames),
            "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-an", out]
    run(cmd)


def part_paths(vdir, i):
    return (os.path.join(vdir, "parts", "%03d.mp4" % i), os.path.join(vdir, "parts", "%03d.wav" % i))


def build_scenes(plan, vdir, todo):
    vid = plan["vid"]
    N = len(plan["scenes"])
    used_file = os.path.join(vdir, "used.json")
    used = set(load_json(used_file)) if os.path.exists(used_file) else set()
    gradient_png(os.path.join(WORK, "grad.png"))
    BATCH = 12
    for b0 in range(0, len(todo), BATCH):
        batch = todo[b0:b0 + BATCH]
        texts = [plan["scenes"][i]["text"] for i in batch]
        words = " ".join(texts).split()
        voice = os.path.join(WORK, "voice_%d.wav" % batch[0])
        heard = tts_fish(" ".join(texts), voice)
        total = probe_dur(voice)
        st, matched = word_starts(words, heard, total)
        print("Voice %.1fs, matched %d of %d words" % (total, matched, len(words)))
        pos, first_idx = 0, []
        for t in texts:
            first_idx.append(pos)
            pos += len(t.split())
        bt = []
        for k in range(len(batch)):
            if k == 0:
                bt.append(0.0)
            else:
                bt.append(max(bt[-1] + 0.8, st[first_idx[k]] - 0.08))
        for k, i in enumerate(batch):
            sc = plan["scenes"][i]
            s = bt[k]
            e = bt[k + 1] if k + 1 < len(batch) else total + (0.9 if i == N - 1 else 0.2)
            d_frames = max(int(FPS * 0.8), int(round((e - s) * FPS)))
            d = d_frames / FPS
            rng = random.Random("%s-%d" % (vid, i))
            n_seg = max(1, int(d / SEG_SECONDS + 0.5))
            seg_d = d / n_seg
            n_words = len(sc["text"].split())
            word_rel = [min(max(0.0, st[first_idx[k] + w] - s), d) for w in range(n_words)]
            vis_list = []
            for j in range(n_seg):
                kw = sc["keywords"][j % len(sc["keywords"])]
                vis_list.append(get_visual(kw, seg_d, rng, used))
            first_of_section = (i == 0) or plan["scenes"][i - 1]["sec"] != sc["sec"]
            tag = ("%02d  %s" % (sc["sec"] + 1, plan["headings"][sc["sec"]].upper())) if first_of_section else ""
            sfx = choose_sfx(sc, rng, first_of_section)
            tmp_dir = os.path.join(WORK, "scene")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            os.makedirs(tmp_dir)
            mp4, wav = part_paths(vdir, i)
            make_audio(voice, s, d, sfx, wav + ".tmp.wav")
            render_video(sc, d_frames, word_rel, tag, vis_list, tmp_dir, rng, mp4 + ".tmp.mp4")
            os.replace(wav + ".tmp.wav", wav)
            os.replace(mp4 + ".tmp.mp4", mp4)
            save_json(used_file, sorted(used))
            print("Scene %d/%d done (%.1fs, %d visuals%s)" % (i + 1, N, d, n_seg, ", sfx" if sfx else ""))


# ---------------------------------------------------------------- final
def fmt_time(t):
    t = int(t)
    return "%d:%02d" % (t // 60, t % 60) if t < 3600 else "%d:%02d:%02d" % (t // 3600, t % 3600 // 60, t % 60)


def pick_music(num):
    for folder in ("music_long", "music"):
        files = sorted(f for e in ("mp3", "m4a", "wav", "ogg") for f in glob.glob(folder + "/*." + e))
        if files:
            return files[num % len(files)]
    return None


def finalize(plan, vdir, privacy, do_upload):
    N = len(plan["scenes"])
    mp4s = [part_paths(vdir, i)[0] for i in range(N)]
    wavs = [part_paths(vdir, i)[1] for i in range(N)]
    durs = [probe_dur(p) for p in mp4s]
    for name, files in (("video.txt", mp4s), ("audio.txt", wavs)):
        with open(os.path.join(WORK, name), "w") as f:
            for p in files:
                f.write("file '%s'\n" % os.path.abspath(p))
    joined_v = os.path.join(WORK, "joined.mp4")
    joined_a = os.path.join(WORK, "joined.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
         os.path.join(WORK, "video.txt"), "-c", "copy", joined_v])
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i",
         os.path.join(WORK, "audio.txt"), "-c", "copy", joined_a])
    total = probe_dur(joined_v)
    num = sum(ord(c) for c in plan["vid"])
    music = pick_music(num)
    out = os.path.join("out", "long.mp4")
    os.makedirs("out", exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", joined_v, "-i", joined_a]
    if music:
        print("Music:", music)
        cmd += ["-stream_loop", "-1", "-i", music, "-filter_complex",
                "[2:a]aformat=sample_fmts=fltp:channel_layouts=stereo,volume=%.3f,afade=t=in:d=2[m];"
                "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[v];"
                "[v][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
                "afade=t=out:st=%.2f:d=3[a]" % (MUSIC_VOL, max(0.0, total - 3)),
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", "%.3f" % total, "-movflags", "+faststart", out]
    run(cmd)
    print("FINAL VIDEO: %s  length %s  size %.1f MB" %
          (out, fmt_time(total), os.path.getsize(out) / 1e6))

    # description with chapters
    meta = plan["meta"]
    desc = str(meta.get("description", plan["title"])).strip()
    sec_start = {}
    t = 0.0
    for i, sc in enumerate(plan["scenes"]):
        sec_start.setdefault(sc["sec"], t)
        t += durs[i]
    if len(sec_start) >= 3:
        desc += "\n\n" + "\n".join("%s %s" % (fmt_time(sec_start[k]), plan["headings"][k])
                                   for k in sorted(sec_start))
    desc += "\n\nStock footage: Pixabay (pixabay.com)."
    tags = [t for t in meta.get("hashtags", []) if isinstance(t, str)]
    tags = ["#" + re.sub(r"[^A-Za-z0-9]", "", t) for t in tags]
    tags = [t for t in tags if len(t) > 1][:3] or ["#motivation", "#selfimprovement", "#mindset"]
    desc += "\n\n" + " ".join(tags)
    script = {"topic": plan["topic"], "category": "motivation",
              "lines": [s["text"] for s in plan["scenes"]],
              "yt": {"title": str(meta.get("title") or plan["title"])[:70],
                     "description": desc,
                     "tags": [str(x) for x in meta.get("tags", [])] or ["motivation", "self improvement"]}}
    spath = os.path.join(vdir, "script.json")
    save_json(spath, script)
    if do_upload:
        subprocess.run([sys.executable, "upload_youtube.py", out, spath, privacy], check=True)
        with open(os.path.join("out", "used_script.txt"), "w") as f:
            f.write(plan.get("script_file", ""))
    else:
        print("Upload skipped (upload=false). Description would be:\n" + desc)
    shutil.rmtree(vdir, ignore_errors=True)
    os.remove(os.path.join(STATE, "current.json"))
    print("Video finished, state cleaned")


# ---------------------------------------------------------------- main
def main():
    days = max(1, int(float(os.environ.get("DAYS") or 5)))
    privacy = (os.environ.get("PRIVACY") or "public").lower()
    do_upload = (os.environ.get("UPLOAD") or "true").lower() != "false"
    fresh = (os.environ.get("FRESH") or "false").lower() == "true"
    for d in (STATE, WORK, "out"):
        os.makedirs(d, exist_ok=True)
    cur = os.path.join(STATE, "current.json")
    if fresh and os.path.exists(cur):
        shutil.rmtree(os.path.join(STATE, load_json(cur)["vid"]), ignore_errors=True)
        os.remove(cur)
        print("Old unfinished video thrown away")
    if os.path.exists(cur):
        vid = load_json(cur)["vid"]
        plan = load_json(os.path.join(STATE, vid, "plan.json"))
        print("Continuing video %s: %s" % (vid, plan["title"]))
    else:
        plan = plan_video()
    vdir = os.path.join(STATE, plan["vid"])
    N = len(plan["scenes"])
    done = [i for i in range(N) if all(os.path.exists(p) for p in part_paths(vdir, i))]
    per_run = math.ceil(N / days)
    todo = [i for i in range(N) if i not in done][:per_run]
    print("Scenes: %d total, %d done, building %d now" % (N, len(done), len(todo)))
    if todo:
        build_scenes(plan, vdir, todo)
    left = [i for i in range(N) if not all(os.path.exists(p) for p in part_paths(vdir, i))]
    if left:
        print("%d scenes still left, will continue in the next run" % len(left))
        return
    finalize(plan, vdir, privacy, do_upload)


if __name__ == "__main__":
    main()
