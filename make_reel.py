import json, random, glob, os, sys, re, difflib, base64, subprocess, time, math
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from moviepy.editor import (AudioFileClip, ImageClip, ColorClip, VideoFileClip,
                            CompositeVideoClip, CompositeAudioClip)
from moviepy.video.fx.all import loop as vloop

W, H = 1080, 1920
TEXT_Y = {"dark": 0.80, "brain": 0.15}
ACCENT = {"dark": (120, 220, 255), "brain": (255, 214, 64)}
UPPER = True
VOICE_LUFS = -16      # voice loudness (fixed)
MUSIC_LUFS = -29      # background music loudness: MORE NEGATIVE = QUIETER (-32 quieter, -26 louder)
SEG_MAX = 3.0         # a new visual at least every ~3 seconds
PX_KEY = os.environ.get("PIXABAY_API_KEY", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"
FALLBACK_KW = {
    "dark": ["lonely man silhouette", "rain window night", "city night walking",
             "dark street alone", "man thinking dark", "empty room", "foggy road night",
             "shadow wall", "sad man sitting"],
    "brain": ["meditation sunrise", "mountain mist", "forest light rays", "calm lake",
              "monk meditation", "ocean waves sunset", "river stream", "clouds sky",
              "candle flame"],
}
PX_CACHE = {}
MAX_WORDS = 3

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
print("Font:", FONT)

def pick(folder, exts, num=0, name=None, tag=None):
    """Pick a file for this script (not random): the script can name one
    ("background"/"music" in script.json), otherwise it follows the script
    text (tag) and then rotates by script number so reels differ."""
    files = sorted(f for e in exts for f in glob.glob(os.path.join(folder, "*." + e)))
    if name:
        hit = [f for f in files if name.lower() in os.path.basename(f).lower()]
        if hit:
            return hit[0]
    if tag:
        hit = [f for f in files if tag in os.path.basename(f).lower()]
        if hit:
            files = hit
    return files[num % len(files)]

REL_WORDS = {"relationship", "relationships", "love", "partner", "ex", "dating",
             "attention", "chase", "chasing", "toxic", "breakup", "heart",
             "miss", "text", "texting", "friend", "friends", "people",
             "boundaries", "respect", "ignore", "ignored", "trust", "jealous"}

def music_tag(data):
    words = re.findall(r"[a-z]+", (" ".join(data["lines"]) + " " +
                       data.get("topic", "")).lower())
    hits = sum(1 for w in words if w in REL_WORDS)
    return "relationship" if hits >= 2 else "psychology"

def text_img(text, accent, size=100, max_w=920):
    font = ImageFont.truetype(FONT, size)
    words = (text.upper() if UPPER else text).split()
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
    key = max(range(len(words)),
              key=lambda i: len(re.sub(r"[^A-Za-z0-9]", "", words[i])))
    lh, pad = int(size * 1.25), 40
    layer = Image.new("RGBA", (W, lh * len(lines) + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    gi = 0
    for li, ln in enumerate(lines):
        lw = sum(meas.textlength(w, font=font) for w in ln) + space * (len(ln) - 1)
        x, y = (W - lw) / 2, pad + li * lh
        for w in ln:
            col = accent if gi == key else (255, 255, 255)
            d.text((x, y), w, font=font, fill=col,
                   stroke_width=7, stroke_fill=(0, 0, 0))
            x += meas.textlength(w, font=font) + space
            gi += 1
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", layer.size, (0, 0, 0, 200)), (0, 10),
                 layer.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    return np.array(Image.alpha_composite(shadow, layer))

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

def make_chunks(lines, maxw=MAX_WORDS):
    out, idx = [], 0
    for l in lines:
        ws = l.split()
        cur, first = [], idx
        for k, w in enumerate(ws):
            if not cur:
                first = idx
            cur.append(w)
            idx += 1
            if len(cur) >= maxw or re.search(r"[,.!?;:]$", w) or k == len(ws) - 1:
                out.append((" ".join(cur), first))
                cur = []
    return out

def tts_fish(text, out_path):
    key = os.environ["FISH_API_KEY"]
    voice_id = os.environ["FISH_VOICE_ID"]
    model = os.environ.get("FISH_MODEL") or "s2.1-pro-free"
    r = requests.post(
        "https://api.fish.audio/v1/tts/stream/with-timestamp",
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json", "model": model},
        json={"text": text, "reference_id": voice_id,
              "format": "mp3", "latency": "normal"},
        stream=True, timeout=300)
    if r.status_code != 200:
        raise SystemExit("Fish API error %s: %s" % (r.status_code, r.text[:300]))
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
    raw = "out/voice_raw.mp3"
    with open(raw, "wb") as f:
        f.write(b"".join(audio))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw,
                    "-ar", "44100", "-ac", "1", out_path], check=True)
    heard = []
    for seq in sorted(align):
        off, segs = align[seq]
        for s in segs:
            heard.append((s["text"], s["start"] + off, s["end"] + off))
    print("Fish words:", len(heard))
    return heard

def whisper_times(words_txt, lines, audio_path, total):
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(
            audio_path, word_timestamps=True, language="en",
            initial_prompt=" ".join(lines), condition_on_previous_text=False)
        heard = [(w.word, w.start, w.end) for s in segs for w in s.words]
        return word_starts(words_txt, heard, total)
    except Exception as e:
        print("Whisper failed, using fallback:", e)
        return word_starts(words_txt, [], total)

# ------------------------------------------------------------ audio levels
def loudnorm_file(src_path, dst_path, lufs, tp=-2.0, start=0.0, length=None,
                  loop_src=False, fade=False):
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if loop_src:
        cmd += ["-stream_loop", "-1"]
    if start:
        cmd += ["-ss", "%.2f" % start]
    cmd += ["-i", src_path]
    if length:
        cmd += ["-t", "%.2f" % length]
    flt = "loudnorm=I=%s:TP=%s:LRA=7" % (lufs, tp)
    if fade and length:
        flt += ",afade=t=in:d=0.6,afade=t=out:st=%.2f:d=1.5" % max(length - 1.5, 0)
    cmd += ["-af", flt, "-ar", "44100", "-ac", "2", dst_path]
    subprocess.run(cmd, check=True)

# ------------------------------------------------------------ visuals (Pixabay)
def groq_keywords(lines, cat):
    """One small Groq call: 3 Pixabay search words per script line."""
    if not GROQ_KEY:
        return None
    numbered = "\n".join("%d) %s" % (i + 1, l) for i, l in enumerate(lines))
    mood = ("dark, moody, lonely, night, shadows" if cat == "dark"
            else "calm, peaceful, nature, meditation, light")
    prompt = ("For each numbered line of a short video script, give 3 different stock-footage "
              "search queries (2 or 3 simple English words each) for things that can be SEEN "
              "(person, place, object, nature, weather). Match the meaning of the line. "
              "Overall mood: " + mood + ". No abstract words, no names, no brands.\n\n"
              + numbered + "\n\nReply with JSON only: {\"k\": [[\"q1\", \"q2\", \"q3\"], ...]} "
              "with exactly %d lists." % len(lines))
    body = {"model": GROQ_MODEL, "temperature": 0.6, "max_completion_tokens": 1800,
            "messages": [{"role": "user", "content": prompt}]}
    if "gpt-oss" in GROQ_MODEL:
        body["reasoning_effort"] = "low"
    for _ in range(3):
        try:
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": "Bearer " + GROQ_KEY,
                                       "Content-Type": "application/json"},
                              json=body, timeout=90)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(15)
                continue
            if r.status_code != 200:
                print("Groq keyword error:", r.status_code, r.text[:150])
                return None
            txt = r.json()["choices"][0]["message"]["content"]
            data = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
            ks = data["k"]
            out = []
            for k in ks[:len(lines)]:
                k = [re.sub(r"[^a-zA-Z ]", "", str(x)).strip().lower() for x in k]
                out.append([x for x in k if x][:3])
            while len(out) < len(lines):
                out.append([])
            return out
        except Exception as e:
            print("Groq keyword problem:", str(e)[:120])
            time.sleep(3)
    return None

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
    words = q.split()
    tries = [q]
    if len(words) > 1:
        tries.append(" ".join(words[:2]))
        tries.append(words[0])
    for qq in tries:
        key = (kind, qq)
        if key in PX_CACHE:
            hits = PX_CACHE[key]
        else:
            params = {"key": PX_KEY, "q": qq, "per_page": 20, "safesearch": "true"}
            if kind == "video":
                data = px_get("https://pixabay.com/api/videos/", params)
            else:
                params.update({"image_type": "photo", "orientation": "vertical",
                               "min_height": 1200})
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

def local_visual(num, name=None):
    files = [f for e in ("png", "jpg", "jpeg") for f in glob.glob("backgrounds/*/*." + e)]
    if not files:
        raise SystemExit("No Pixabay result and no backgrounds/ images to fall back on")
    files.sort()
    return {"kind": "image", "path": files[num % len(files)], "id": "local"}

def get_visual(kw, d, rng, used, num):
    if not PX_KEY or not kw:
        return local_visual(num)
    order = ["video", "image"] if rng.random() < 0.8 else ["image", "video"]
    for kind in order:
        hits = px_search(kind, kw)
        hits = [h for h in hits if kind == "image" or h.get("duration", 99) >= d]
        fresh = [h for h in hits if "%s%s" % (kind[0], h["id"]) not in used]
        pool = (fresh or hits)[:10]
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
                path = download(url, os.path.join("work", "clips", uid + ".mp4"))
            else:
                url = h.get("largeImageURL") or h.get("webformatURL")
                if not url:
                    continue
                path = download(url, os.path.join("work", "clips", uid + ".jpg"))
            if not path:
                continue
            used.add(uid)
            return {"kind": kind, "path": path, "id": uid}
    print("No Pixabay result for %r, using local background" % kw)
    return local_visual(num)

def cover_image(path):
    img = Image.open(path).convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
    x, y = (img.width - W) // 2, (img.height - H) // 2
    return np.array(img.crop((x, y, x + W, y + H)))

def piece_clip(vis, t0, d):
    if vis["kind"] == "video":
        c = VideoFileClip(vis["path"], audio=False)
        if c.duration < d + 0.1:
            c = vloop(c, duration=d + 0.1)
        else:
            st = random.uniform(0, max(c.duration - d - 0.1, 0))
            c = c.subclip(st, st + d + 0.1)
        if c.w / c.h > W / H:
            cw = int(c.h * W / H) // 2 * 2
            x1 = (c.w - cw) // 2
            c = c.crop(x1=x1, x2=x1 + cw)
        else:
            ch = int(c.w * H / W) // 2 * 2
            y1 = (c.h - ch) // 2
            c = c.crop(y1=y1, y2=y1 + ch)
        c = c.resize((W, H))
        return c.set_start(t0).set_duration(d)
    c = ImageClip(cover_image(vis["path"])).set_duration(d)
    c = c.resize(lambda t: 1 + 0.06 * t / d).set_position("center")
    return c.set_start(t0)

def plan_pieces(lines, wst, dur):
    """Cut the reel into pieces of at most SEG_MAX seconds, a new piece at every line start."""
    starts, idx = [], 0
    for l in lines:
        starts.append(0.0 if idx == 0 else wst[min(idx, len(wst) - 1)])
        idx += len(l.split())
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1] + 0.3)
    ends = starts[1:] + [dur]
    pieces = []
    for i, (a, b) in enumerate(zip(starts, ends)):
        span = max(b - a, 0.3)
        n = max(1, int(math.ceil(span / SEG_MAX)))
        for k in range(n):
            pieces.append((i, k, a + span * k / n, span / n))
    return pieces

def build_visuals(lines, wst, dur, cat, num):
    rng = random.Random(num * 7919 + 13)
    kws = groq_keywords(lines, cat)
    if not kws:
        print("Using built-in keywords")
        kws = [[] for _ in lines]
    bank = FALLBACK_KW.get(cat, FALLBACK_KW["dark"])
    used, clips = set(), []
    for (li, k, t0, d) in plan_pieces(lines, wst, dur):
        mine = kws[li] if li < len(kws) else []
        kw = mine[k % len(mine)] if mine else bank[(num + li + k) % len(bank)]
        vis = get_visual(kw, d, rng, used, num + li + k)
        print("Visual %.1fs +%.1fs: %s -> %s" % (t0, d, kw, vis["id"]))
        try:
            clips.append(piece_clip(vis, t0, d))
        except Exception as e:
            print("Clip failed (%s), using local image" % str(e)[:100])
            clips.append(piece_clip(local_visual(num + li + k), t0, d))
    return clips

def main():
    folder = ("queue/%03d" % int(sys.argv[1])) if len(sys.argv) > 1 and sys.argv[1].strip().isdigit() \
             else sorted(glob.glob("queue/*/"))[-1]
    data = json.load(open(os.path.join(folder, "script.json"), encoding="utf-8"))
    cat = data.get("category", "dark")
    num = int(os.path.basename(folder.rstrip("/")))
    lines = data["lines"]
    words_txt = " ".join(lines).split()
    os.makedirs("out", exist_ok=True)

    if data.get("tts") == "fish":
        voice_path = "out/voice.mp3"
        heard = tts_fish(" ".join(lines), voice_path)
        loudnorm_file(voice_path, "out/voice_norm.wav", VOICE_LUFS, tp=-1.5)
        voice_path = "out/voice_norm.wav"
        voice = AudioFileClip(voice_path)
        wst, matched = word_starts(words_txt, heard, voice.duration)
    else:
        voice_path = glob.glob(os.path.join(folder, "voice.*"))[0]
        voice = AudioFileClip(voice_path)
        wst, matched = whisper_times(words_txt, lines, voice_path, voice.duration)
    print("Matched", matched, "of", len(words_txt), "words")
    dur = voice.duration + 1.0

    vis_clips = build_visuals(lines, wst, dur, cat, num)
    dim = ColorClip((W, H), color=(0, 0, 0)).set_opacity(0.35).set_duration(dur)

    chunks = make_chunks(lines)
    starts = [max(0.0, wst[fi] - 0.05) for _, fi in chunks]
    starts[0] = 0.0
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1] + 0.15)
    print("Chunk starts:", [(c[0], round(t, 2)) for c, t in zip(chunks, starts)])

    cy = TEXT_Y.get(cat, 0.5) * H
    acc = ACCENT.get(cat, (255, 214, 64))
    sc = lambda t: 0.88 + 0.12 * min(t / 0.12, 1.0)
    clips = []
    for i, (txt, _) in enumerate(chunks):
        st = starts[i]
        en = starts[i + 1] if i + 1 < len(chunks) else dur
        arr = text_img(txt, acc)
        h = arr.shape[0]
        c = (ImageClip(arr).resize(sc)
             .set_position(lambda t, h=h: ("center", cy - h * sc(t) / 2))
             .set_start(st).set_duration(max(en - st, 0.15)))
        clips.append(c)

    mpath = pick("music", ["mp3", "m4a", "wav", "ogg"], num,
                 data.get("music"), music_tag(data))
    print("Music:", mpath, "| Background:", cat)
    mdur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", mpath],
        stdout=subprocess.PIPE, text=True).stdout.strip() or 0)
    if mdur > dur + 3:
        t0, looping = random.uniform(0, mdur - dur - 1), False
    else:
        t0, looping = 0.0, True
    loudnorm_file(mpath, "out/music_norm.wav", MUSIC_LUFS, tp=-3.0, start=t0,
                  length=dur, loop_src=looping, fade=True)
    bgm = AudioFileClip("out/music_norm.wav")
    audio = CompositeAudioClip([bgm, voice])

    video = (CompositeVideoClip(vis_clips + [dim] + clips, size=(W, H))
             .set_duration(dur).set_audio(audio))
    video.write_videofile("out/reel.mp4", fps=24, codec="libx264",
                          audio_codec="aac", preset="veryfast",
                          ffmpeg_params=["-pix_fmt", "yuv420p"])

main()
