import json, os, sys, re, glob, random, difflib, time
import requests

KEY = os.environ["GROQ_API_KEY"]
MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"
HEADER = "Psychology Says:"

TOPICS = {
    "dark": [
        "chasing someone's attention", "being always available", "constant criticism",
        "people pleasing", "forgiving without trusting again", "closure",
        "setting boundaries", "the silent treatment", "one-sided effort",
        "over-explaining yourself", "ghosting", "missing people who hurt you",
        "fake friends", "being the strong one for everyone",
        "apologies without change", "outgrowing old friends", "jealousy",
        "feeling lonely in a relationship", "expectations vs reality in love",
        "why some people change after they get what they want",
        "protecting your energy", "mixed signals", "self-respect after rejection",
        "walking away without explaining", "feeling replaceable",
        "how you treat yourself teaches others how to treat you",
        "love vs habit", "ignoring red flags", "moving on slowly",
    ],
    "brain": [
        "procrastination", "decision fatigue", "comparing yourself to others",
        "trying to control everything", "overthinking at night", "perfectionism",
        "fear of failure", "motivation vs discipline", "habits and identity",
        "burnout", "negative self-talk", "phone and boredom", "multitasking",
        "first impressions", "remembering embarrassing moments",
        "waiting for the right time", "small wins", "the comfort zone",
        "fear of judgment", "feeling like a fraud", "rereading old messages",
        "wanting what you can't have", "regret", "fresh starts",
        "gratitude", "how your environment shapes your mood",
        "distractions and focus", "how mornings set the tone",
        "why we avoid what matters most",
    ],
}

CAT_DESC = {
    "dark": "relationships, people, boundaries and self-respect",
    "brain": "the mind, habits, focus and emotions",
}

def fold(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()

def folder_num(p):
    return int(os.path.basename(os.path.dirname(p)))

def all_scripts():
    paths = [p for p in glob.glob("queue/*/script.json") + glob.glob("done/*/script.json")
             if os.path.basename(os.path.dirname(p)).isdigit()]
    out = []
    for p in sorted(paths, key=folder_num):
        try:
            out.append(json.load(open(p, encoding="utf-8")))
        except Exception:
            pass
    return out

def next_number():
    nums = [int(os.path.basename(p)) for p in glob.glob("queue/*") + glob.glob("done/*")
            if os.path.basename(p).isdigit()]
    return (max(nums) if nums else 0) + 1

def load_examples():
    p = "style/examples.txt"
    if not os.path.exists(p):
        return []
    out = []
    for b in re.split(r"\n\s*---\s*\n", open(p, encoding="utf-8").read()):
        b = b.strip()
        if fold(b.split("\n")[0]).startswith("psychology says"):
            b = "\n".join(b.split("\n")[1:]).strip()
        if b:
            out.append(b)
    return out

def strip_header(lines):
    if lines and fold(lines[0]).startswith("psychology says"):
        return lines[1:]
    return lines

def ask(system, user):
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
        json={"model": MODEL,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}],
              "temperature": 0.8, "max_completion_tokens": 2500},
        timeout=120)
    if r.status_code != 200:
        raise SystemExit("Groq error %s: %s" % (r.status_code, r.text[:300]))
    return r.json()["choices"][0]["message"]["content"]

def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("reply was not JSON")
    d = json.loads(m.group(0))
    lines = [str(x).strip() for x in d["lines"] if str(x).strip()]
    caption = str(d.get("caption", "")).strip()
    tags = str(d.get("hashtags", "")).strip() or \
        "#psychology #mindset #selfgrowth #relationships #mentalstrength"
    return lines, caption, tags

def check(lines, caption, prev_texts, prev_lines, prev_last):
    """Return None if the script is fine, else the reason it was rejected."""
    lines = strip_header(lines)
    if not 5 <= len(lines) <= 15:
        return "use 5 to 15 short lines (you used %d)" % len(lines)
    total = len(" ".join(lines).split())
    if not 35 <= total <= 90:
        return "the script must be 35 to 90 words (you used %d)" % total
    for l in lines:
        n = len(l.split())
        if n < 2 or n > 10:
            return "every line must be 2 to 10 words, fix this line: " + l
        if re.search(r"[^\x00-\x7F\u2018\u2019\u201C\u201D\u2013\u2014]", l):
            return "no emojis or special symbols: " + l
        if re.search(r"[A-Za-z]{16,}", l):
            return "use simpler, shorter words in this line: " + l
        if re.search(r"%|\d|studies|research|scientist|proven|according to", l, re.I):
            return "no numbers, statistics or study claims: " + l
        if len(fold(l).split()) >= 4 and fold(l) in prev_lines:
            return "this line was already used before: " + l
    if not caption:
        return "caption is missing"
    txt = fold(" ".join(lines))
    for p in prev_texts:
        if difflib.SequenceMatcher(None, txt, p).ratio() > 0.5:
            return "too similar to an earlier script, use a completely new angle"
    last = fold(lines[-1])
    for p in prev_last:
        if difflib.SequenceMatcher(None, last, p).ratio() > 0.7:
            return "the closing line is too similar to an earlier closing line"
    return None

def pick_topic(cat, recent):
    pool = TOPICS[cat]
    used = [s.get("topic") for s in recent if s.get("category") == cat]
    fresh = [t for t in pool if t not in used]
    if fresh:
        return random.choice(fresh)
    return min(pool, key=lambda t: used.index(t) if t in used else -1)

def make_one(recent, examples):
    cat = random.choice(["dark", "brain"])
    topic = pick_topic(cat, recent)

    prev_texts = [fold(" ".join(strip_header(s.get("lines", [])))) for s in recent]
    prev_texts += [fold(e.replace("\n", " ")) for e in examples]
    prev_lines = set()
    prev_last = []
    for s in recent:
        ls = strip_header(s.get("lines", []))
        prev_lines.update(fold(l) for l in ls)
        if ls:
            prev_last.append(fold(ls[-1]))
    for e in examples:
        ls = [l for l in e.split("\n") if l.strip()]
        prev_lines.update(fold(l) for l in ls)
        prev_last.append(fold(ls[-1]))

    shown = random.sample(examples, min(5, len(examples)))
    ex_txt = "\n\n".join("Example %d:\n%s\n%s" % (i + 1, HEADER, e)
                         for i, e in enumerate(shown))
    avoid = [" ".join(strip_header(s.get("lines", []))[:2]) for s in recent[-40:]]

    system = ("You write short Instagram Reel scripts in the 'Psychology Says' style. "
              "You follow every rule exactly. Reply with JSON only.")
    base = "Write ONE new script about: " + topic + "\nArea: " + CAT_DESC[cat] + "\n"
    if ex_txt:
        base += ("\nThese example scripts show the exact style, rhythm and line length. "
                 "Match the style, but NEVER copy their words, ideas or endings:\n\n"
                 + ex_txt + "\n")
    base += """
STRICT RULES:
1. Write only the lines AFTER the opening "Psychology Says:" (do not include that opening).
2. 5 to 15 short lines, each line 2 to 10 words, 40 to 90 words in total.
3. Very simple, everyday English. Short common words. No jargon or psychology terms.
4. Flow: a relatable observation, then a turn (like "But" or "Sometimes"), then a deeper insight, then a memorable closing line. Make the closing line different from the examples.
5. Soft, honest wording (often, sometimes, can, may). No numbers, no statistics, no "studies show", no diagnosis, no advice that hurts or manipulates anyone.
6. No emojis. No hashtags inside the lines.
7. Pick a fresh angle on the topic. Never reuse these earlier openings or ideas:
"""
    base += "\n".join("- " + a for a in avoid) if avoid else "- (none yet)"
    base += ('\n\nReturn exactly this JSON: {"lines": ["..."], "caption": "1 to 2 simple '
             'sentences ending with a call to save or share", "hashtags": "#a #b #c #d #e"}')

    reason = None
    for attempt in range(6):
        user = base
        if reason:
            user += "\n\nYour last attempt was rejected: " + reason + ". Fix it."
        try:
            lines, caption, tags = parse(ask(system, user))
        except SystemExit:
            raise
        except Exception as e:
            reason = "bad output (" + str(e) + ")"
            print("retry:", reason)
            continue
        reason = check(lines, caption, prev_texts, prev_lines, prev_last)
        if reason:
            print("retry:", reason)
            continue
        return {"category": cat, "topic": topic, "tts": "fish",
                "lines": [HEADER] + strip_header(lines),
                "caption": caption, "hashtags": tags}
    return None

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    examples = load_examples()
    print("Loaded examples:", len(examples))
    for _ in range(n):
        item = make_one(all_scripts(), examples)
        if not item:
            print("Could not make a good script, skipping")
            continue
        num = "%03d" % next_number()
        os.makedirs("queue/" + num, exist_ok=True)
        with open("queue/%s/script.json" % num, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        print("Created queue/" + num, "-", item["topic"])
        time.sleep(2)

main()
