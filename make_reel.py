import json, random, glob, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import (AudioFileClip, ImageClip, ColorClip,
                            CompositeVideoClip, CompositeAudioClip)
from moviepy.audio.fx.all import audio_loop

W, H = 1080, 1920
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
TEXT_Y = {"dark": 0.15, "brain": 0.80}  # screen ka kitna hissa (0=upar, 1=neeche)
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

def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("queue/*/"))[0]
    data = json.load(open(os.path.join(folder, "script.json"), encoding="utf-8"))
    cat = data.get("category", "dark")

    voice = AudioFileClip(glob.glob(os.path.join(folder, "voice.*"))[0])
    dur = voice.duration + 1.0

    img = Image.open(pick("backgrounds/" + cat, ["png", "jpg", "jpeg"])).convert("RGB")
    s = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1))
    bg = ImageClip(np.array(img)).set_duration(dur)
    bg = bg.resize(lambda t: 1 + 0.06 * t / dur).set_position("center")
    dim = ColorClip((W, H), color=(0, 0, 0)).set_opacity(0.25).set_duration(dur)

    lines = data["lines"]
    total = sum(len(l) for l in lines)
    py = TEXT_Y.get(cat, 0.5)
    clips, t = [], 0.0
    for i, l in enumerate(lines):
        end = dur if i == len(lines) - 1 else t + voice.duration * len(l) / total
        arr = text_img(l)
        c = (ImageClip(arr).set_start(t).set_duration(end - t).crossfadein(0.3)
             .set_position(("center", py * H - arr.shape[0] / 2)))
        clips.append(c)
        t = end

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
