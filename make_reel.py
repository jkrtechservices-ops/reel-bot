import json, random, glob, os, sys, re, difflib
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (AudioFileClip, ImageClip, ColorClip,
                            CompositeVideoClip, CompositeAudioClip)
from moviepy.audio.fx.all import audio_loop

W, H = 1080, 1920
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TEXT_Y = {"dark": 0.15, "brain": 0.80}
MUSIC_VOL = 0.15

def pick(folder, exts):
    files = [f for e in exts for f in glob.glob(os.path.join(folder, "*." + e))]
    return random.choice(files)

def text_img(text, size=72, max_w=900):
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
    lh = int(size * 1.35)
    img = Image.new("RGBA", (W, lh * len(lines) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i, l in enumerate(lines):
        tw = d.textlength(l, font=font)
        d.text(((W - tw) / 2, 20 + i * lh), l, font=font,
               fill="white", stroke_width=5, stroke_fill="black")
    return np.array(img)

def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())

def starts_from_words(lines, words, total):
    words = [(norm(t), s, e) for t, s, e in words if norm(t)]
    toks = [(norm(w), li) for li, l in enumerate(lines)
            for w in l.split() if norm(w)]
    a = [t[0] for t in toks]
    b = [w[0] for w in words]
    tstart = [None] * len(a)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            tstart[blk.a + k] = words[blk.b + k][1]
    starts = []
    for li in range(len(lines)):
        idx = [i for i, t in enumerate(toks) if t[1] == li]
        starts.append(next((tstart[i] for i in idx if tstart[i] is not None), None))
    starts[0] = 0.0
    chars = [len(l) for l in lines]
    for i in range(1, len(lines)):
        if starts[i] is None:
            p = max(j for j in range(i) if starts[j] is not None)
            n = next((j for j in range(i + 1, len(lines)) if starts[j] is not None), None)
            end_t = starts[n] if n is not None else total
            span = sum(chars[p:(n if n is not None else len(lines))])
            starts[i] = starts[p] + (end_t - starts[p]) * sum(chars[p:i]) / span
    starts = [max(0.0, s - 0.08) if i else 0.0 for i, s in enumerate(starts)]
    for i in range(1, len(starts)):
        starts[i] = max(starts[i], starts[i - 1] + 0.3)
    return starts

def get_starts(lines, audio_path, total):
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segs, _ = model.transcribe(audio_path, word_timestamps=True, language="en")
        words = [(w.word, w.start, w.end) for s in segs for w in s.words]
        print("Whisper words:", len(words))
        return starts_from_words(lines, words, total)
    except Exception as e:
        print("Whisper failed, using fallback:", e)
        chars = [len(l) for l in lines]
        tot, acc, out = sum(chars), 0, []
        for c in chars:
            out.append(total * acc / tot)
            acc += c
        return out

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("queue/*/"))[0]
    data = json.load(open(os.path.join(folder, "script.json"), encoding="utf-8"))
    cat = data.get("category", "dark")

    voice_path = glob.glob(os.path.join(folder, "voice.*"))[0]
    voice = AudioFileClip(voice_path)
    dur = voice.duration + 1.0

    img = Image.open(pick("backgrounds/" + cat, ["png", "jpg", "jpeg"])).convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
    bg = ImageClip(np.array(img)).set_duration(dur)
    bg = bg.resize(lambda t: 1 + 0.06 * t / dur).set_position("center")
    dim = ColorClip((W, H), color=(0, 0, 0)).set_opacity(0.25).set_duration(dur)

    lines = data["lines"]
    starts = get_starts(lines, voice_path, voice.duration)
    print("Line starts:", [round(x, 2) for x in starts])
    py = TEXT_Y.get(cat, 0.5)
    clips = []
    for i, l in enumerate(lines):
        st = starts[i]
        en = starts[i + 1] if i + 1 < len(lines) else dur
        arr = text_img(l)
        c = (ImageClip(arr).set_start(st).set_duration(max(en - st, 0.3))
             .crossfadein(0.2)
             .set_position(("center", py * H - arr.shape[0] / 2)))
        clips.append(c)

    bgm = audio_loop(AudioFileClip(pick("music", ["mp3", "m4a", "wav", "ogg"])),
                     duration=dur).volumex(MUSIC_VOL)
    audio = CompositeAudioClip([bgm, voice])

    video = (CompositeVideoClip([bg, dim] + clips, size=(W, H))
             .set_duration(dur).set_audio(audio))
    os.makedirs("out", exist_ok=True)
    video.write_videofile("out/reel.mp4", fps=24, codec="libx264",
                          audio_codec="aac", preset="veryfast",
                          ffmpeg_params=["-pix_fmt", "yuv420p"])

main()
