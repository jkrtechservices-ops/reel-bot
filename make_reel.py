import json, random, glob, os, sys, re, difflib, base64, subprocess
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (AudioFileClip, ImageClip, ColorClip,
                            CompositeVideoClip, CompositeAudioClip)
from moviepy.audio.fx.all import audio_loop

W, H = 1080, 1920
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TEXT_Y = {"dark": 0.15, "brain": 0.80}
MUSIC_VOL = 0.15
MAX_WORDS = 3

def pick(folder, exts):
    files = [f for e in exts for f in glob.glob(os.path.join(folder, "*." + e))]
    return random.choice(files)

def text_img(text, size=104, max_w=940):
    font = ImageFont.truetype(FONT, size)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lh = int(size * 1.3)
    img = Image.new("RGBA", (W, lh * len(lines) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        tw = d.textlength(l, font=font)
        d.text(((W - tw) / 2, 20 + i * lh), l, font=font,
               fill="white", stroke_width=6, stroke_fill="black")
    return np.array(img)

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

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("queue/*/"))[0]
    data = json.load(open(os.path.join(folder, "script.json"), encoding="utf-8"))
    cat = data.get("category", "dark")
    lines = data["lines"]
    words_txt = " ".join(lines).split()
    os.makedirs("out", exist_ok=True)

    if data.get("tts") == "fish":
        voice_path = "out/voice.mp3"
        heard = tts_fish(" ".join(lines), voice_path)
        voice = AudioFileClip(voice_path)
        wst, matched = word_starts(words_txt, heard, voice.duration)
    else:
        voice_path = glob.glob(os.path.join(folder, "voice.*"))[0]
        voice = AudioFileClip(voice_path)
        wst, matched = whisper_times(words_txt, lines, voice_path, voice.duration)
    print("Matched", matched, "of", len(words_txt), "words")
    dur = voice.duration + 1.0

    img = Image.open(pick("backgrounds/" + cat, ["png", "jpg", "jpeg"])).convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
    bg = ImageClip(np.array(img)).set_duration(dur)
    bg = bg.resize(lambda t: 1 + 0.06 * t / dur).set_position("center")
    dim = ColorClip((W, H), color=(0, 0, 0)).set_opacity(0.25).set_duration(dur)

    chunks = make_chunks(lines)
    starts = [max(0.0, wst[fi] - 0.05) for _, fi in chunks]
    starts[0] = 0.0
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1] + 0.15)
    print("Chunk starts:", [(c[0], round(t, 2)) for c, t in zip(chunks, starts)])

    py = TEXT_Y.get(cat, 0.5)
    clips = []
    for i, (txt, _) in enumerate(chunks):
        st = starts[i]
        en = starts[i + 1] if i + 1 < len(chunks) else dur
        arr = text_img(txt)
        c = (ImageClip(arr).set_start(st).set_duration(max(en - st, 0.15))
             .set_position(("center", py * H - arr.shape[0] / 2)))
        clips.append(c)

    bgm = audio_loop(AudioFileClip(pick("music", ["mp3", "m4a", "wav", "ogg"])),
                     duration=dur).volumex(MUSIC_VOL)
    audio = CompositeAudioClip([bgm, voice])

    video = (CompositeVideoClip([bg, dim] + clips, size=(W, H))
             .set_duration(dur).set_audio(audio))
    video.write_videofile("out/reel.mp4", fps=24, codec="libx264",
                          audio_codec="aac", preset="veryfast",
                          ffmpeg_params=["-pix_fmt", "yuv420p"])

main()
