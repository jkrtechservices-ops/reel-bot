import json, os, re, glob, random

HEADERS = {"dark": "Psychology Says:", "brain": "Buddha Wisdom:"}
HEADER_STARTS = ("psychology says", "buddha wisdom")
CTAS = {
    "dark": ["Follow for more daily psychology about people and relationships.",
             "Follow for more daily videos that help you understand people.",
             "Follow for more daily life changing videos."],
    "brain": ["Follow for more daily Buddha wisdom for real life.",
              "Follow for more daily life changing wisdom.",
              "Follow if this touched your heart."],
}
TAGS = {"dark": "#darkpsychology #psychologyfacts #relationships #selfrespect #mindset",
        "brain": "#buddha #buddhawisdom #lifelessons #innerpeace #mindset"}
CAPTIONS = {"dark": "If this felt like you, save it and send it to someone who needs to hear it.",
            "brain": "Read this slowly. Save it for the day you need it."}

def fold(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def clean(l):
    """Make one pasted line safe: no markdown, bullets, numbering, emojis, stray quotes or commas."""
    l = l.replace("\u00a0", " ").strip()
    l = re.sub(r"\*+|_{2,}|`", "", l)
    l = re.sub(r"^\s*([-\u2022\u2013\u25cf>]+)\s+", "", l)
    l = re.sub(r"^\s*\d{1,3}\s*[\.\)]\s*", "", l)
    l = re.sub(r"(?i)^\s*(hook|line\s*\d+|voiceover|voice over|narration|text)\s*[:\-]\s*", "", l)
    l = re.sub(r"[^\x00-\x7F\u2018\u2019\u201C\u201D\u2013\u2014]", "", l)
    l = re.sub(r",\s*$", "", l.strip()).strip()
    if l.count('"') % 2 == 1:
        if l.startswith('"'):
            l = l[1:]
        elif l.endswith('"'):
            l = l[:-1]
    elif len(l) > 1 and l.startswith('"') and l.endswith('"'):
        l = l[1:-1]
    return l.strip()

LABEL = re.compile(r"(?i)^\W*(script|reel|story|video|day|part)\s*#?\s*\d*\W*$")

def next_number():
    nums = [int(os.path.basename(p)) for p in glob.glob("queue/*") + glob.glob("done/*")
            if os.path.basename(p).isdigit()]
    return (max(nums) if nums else 0) + 1

def json_items(text):
    """Every {...} object that has a 'lines' list, wherever it sits in the text."""
    dec, out, i = json.JSONDecoder(), [], 0
    while True:
        i = text.find("{", i)
        if i < 0:
            return out
        try:
            obj, end = dec.raw_decode(text, i)
            if isinstance(obj, dict) and isinstance(obj.get("lines"), list):
                out.append(obj)
            i = end
        except Exception:
            i += 1

def split_blocks(text):
    text = "\n".join(l for l in text.replace("\r", "").split("\n") if not l.strip().startswith("//"))
    if re.search(r"(?m)^\s*-{3,}\s*$", text):
        return [b for b in re.split(r"(?m)^\s*-{3,}\s*$", text) if b.strip()]
    lines = text.split("\n")
    for test in (lambda l: fold(clean(l)).startswith(HEADER_STARTS),
                 lambda l: bool(LABEL.match(l.strip())),
                 lambda l: bool(re.match(r"^\s*\W{0,3}\d{1,3}\s*[\.\)]?\W{0,3}\s*$", l))):
        idx = [i for i, l in enumerate(lines) if l.strip() and test(l)]
        if len(idx) >= 2:
            idx.append(len(lines))
            return ["\n".join(lines[idx[k]:idx[k + 1]]) for k in range(len(idx) - 1)]
    return [b for b in re.split(r"\n\s*\n", text) if b.strip()]

def from_text(b):
    cat, caption, tags, lines = None, "", "", []
    for raw in b.split("\n"):
        if not raw.strip() or LABEL.match(raw.strip()):
            continue
        m = re.match(r"(?i)^\W*(category|caption|hashtags?)\s*:\s*(.*)$", raw)
        if m:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k == "category":
                cat = "brain" if re.search(r"brain|buddha", v, re.I) else "dark"
            elif k == "caption":
                caption = v
            else:
                tags = v
            continue
        l = clean(raw)
        if l.lower() in ("dark", "brain") and not lines and not cat:
            cat = l.lower()
            continue
        if l and not re.match(r"(?i)^(title|script|reel)\s*\d*\s*:", l):
            lines.append(l)
    if len(lines) < 3 and lines:
        sent = re.split(r"(?<=[.!?])\s+", " ".join(lines))
        lines = [s.strip() for s in sent if s.strip()]
    return cat, lines, caption, tags

def from_json(d):
    cat = d.get("category") if d.get("category") in HEADERS else None
    return cat, [clean(str(x)) for x in d["lines"] if clean(str(x))], d.get("caption", ""), d.get("hashtags", "")

def build(cat, lines, caption, tags):
    if lines and fold(lines[0]).startswith(HEADER_STARTS):
        if cat is None:
            cat = "brain" if fold(lines[0]).startswith("buddha") else "dark"
        rest = re.sub(r"(?i)^\s*(psychology says|buddha wisdom)\s*:?\s*", "", lines[0]).strip()
        lines = ([rest] if rest else []) + lines[1:]
    if cat is None:
        cat = "brain" if re.search(r"(?i)\b(buddha|monk|zen)\b", " ".join(lines)) else "dark"
    cta = None
    if lines and fold(lines[-1]).startswith("follow"):
        cta, lines = lines[-1], lines[:-1]
    if len(lines) < 3:
        return None
    cta = cta or random.choice(CTAS[cat])
    return {"category": cat, "topic": "manual", "tts": "fish",
            "lines": [HEADERS[cat]] + lines + [cta], "cta": cta,
            "caption": caption or CAPTIONS[cat], "hashtags": tags or TAGS[cat]}

def main():
    if not os.path.exists("inbox.txt"):
        print("No inbox.txt")
        return
    text = open("inbox.txt", encoding="utf-8").read()
    objs = json_items(text)
    parsed = [from_json(o) for o in objs] if objs else [from_text(b) for b in split_blocks(text)]
    made = skipped = 0
    for p in parsed:
        if not p[1]:
            continue
        item = build(*p)
        if not item:
            skipped += 1
            print("Skipped one block (fewer than 3 lines):", " | ".join(p[1])[:80])
            continue
        num = "%03d" % next_number()
        os.makedirs("queue/" + num, exist_ok=True)
        with open("queue/%s/script.json" % num, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        print("Created queue/%s (%s, %d lines): %s" % (num, item["category"], len(item["lines"]), item["lines"][1][:50]))
        made += 1
    if made:
        open("inbox.txt", "w", encoding="utf-8").write(INBOX_HELP)
    print("Imported: %d, skipped: %d" % (made, skipped))

INBOX_HELP = """// Yahan scripts paste karo, kisi bhi format mein (bot khud theek kar leta hai).
// Behtar: do scripts ke beech ek line mein --- likho.
// Commit karte hi scripts queue mein chali jayengi aur ye file khali ho jayegi.
"""

if __name__ == "__main__":
    main()
