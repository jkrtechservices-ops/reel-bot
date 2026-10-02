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
    l = l.strip().replace("\u00a0", " ")
    l = re.sub(r",\s*$", "", l).strip()
    if l.count('"') % 2 == 1:
        if l.startswith('"'):
            l = l[1:]
        elif l.endswith('"'):
            l = l[:-1]
    elif len(l) > 1 and l.startswith('"') and l.endswith('"'):
        l = l[1:-1]
    return l.strip()

def next_number():
    nums = [int(os.path.basename(p)) for p in glob.glob("queue/*") + glob.glob("done/*")
            if os.path.basename(p).isdigit()]
    return (max(nums) if nums else 0) + 1

def split_blocks(text):
    text = "\n".join(l for l in text.replace("\r", "").split("\n") if not l.strip().startswith("//"))
    return [b.strip() for b in re.split(r"(?m)^\s*-{3,}\s*$", text) if b.strip()]

def from_json(b):
    try:
        d = json.loads(b)
    except Exception:
        return None
    if not isinstance(d, dict) or not d.get("lines"):
        return None
    cat = d.get("category") if d.get("category") in HEADERS else "dark"
    return cat, [clean(x) for x in d["lines"]], d.get("caption", ""), d.get("hashtags", "")

def from_text(b):
    cat, caption, tags, lines = None, "", "", []
    for raw in b.split("\n"):
        if not raw.strip():
            continue
        m = re.match(r"(?i)^\s*(category|caption|hashtags?)\s*:\s*(.*)$", raw)
        if m:
            k, v = m.group(1).lower(), m.group(2).strip()
            if k == "category":
                cat = "brain" if "brain" in v.lower() or "buddha" in v.lower() else "dark"
            elif k == "caption":
                caption = v
            else:
                tags = v
            continue
        l = clean(raw)
        if l.lower() in ("dark", "brain") and not lines and not cat:
            cat = l.lower()
            continue
        if l:
            lines.append(l)
    return cat, lines, caption, tags

def build(cat, lines, caption, tags):
    if lines and fold(lines[0]).startswith(HEADER_STARTS):
        if cat is None:
            cat = "brain" if fold(lines[0]).startswith("buddha") else "dark"
        lines = lines[1:]
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
    made = 0
    for b in split_blocks(text):
        parsed = from_json(b) if b.startswith("{") else from_text(b)
        item = build(*parsed) if parsed else None
        if not item:
            print("Skipped a block (too short or unreadable):", b[:60].replace("\n", " "))
            continue
        num = "%03d" % next_number()
        os.makedirs("queue/" + num, exist_ok=True)
        with open("queue/%s/script.json" % num, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        print("Created queue/%s (%s, %d lines)" % (num, item["category"], len(item["lines"])))
        made += 1
    if made:
        open("inbox.txt", "w", encoding="utf-8").write(INBOX_HELP)
    print("Imported:", made)

INBOX_HELP = """// Yahan scripts paste karo. Ek script = ek block. Do scripts ke beech ek line mein --- likho.
// Pehli line mein dark ya brain likh sakte ho (na likho to bot khud samajh leta hai).
// Optional lines: Caption: ...   Hashtags: ...
// Commit karte hi scripts queue mein chali jayengi aur ye file khali ho jayegi.
"""

if __name__ == "__main__":
    main()
