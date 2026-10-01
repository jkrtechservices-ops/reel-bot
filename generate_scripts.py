import json, os, sys, re, glob, random, difflib, time
import requests

KEY = os.environ["GROQ_API_KEY"]
MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"
SEARCH_MODEL = os.environ.get("GROQ_SEARCH_MODEL") or "groq/compound-mini"
HEADER = "Psychology Says:"
INSPO_SITES = ["reddit.com", "quora.com", "pinterest.com", "goodreads.com"]

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

CTAS = {
    "dark": [
        "Follow for more daily psychology about people and relationships.",
        "Follow for more daily videos that help you understand people.",
        "Follow for more daily psychology that can change your life.",
        "Follow for more daily life changing videos.",
    ],
    "brain": [
        "Follow for more daily psychology about your mind and habits.",
        "Follow for more daily videos that help you understand your mind.",
        "Follow for more daily psychology that can change your life.",
        "Follow for more daily life changing videos.",
    ],
}

PATTERNS = [
    ("The more you do X, the less/more Y happens",
     "Start with 'The more you ___, the ___ you become' (or 'the less ___'). Then 'But when you ___,' "
     "show the surprising result. Then 'Sometimes, ___' with a deeper reason. "
     "End with one calm closing sentence that sums it up."),
    ("Reframe: you are not X, you are just Y",
     "Start with 'Sometimes, you are not ___.' Then 'You are just ___.' Explain what that does to you "
     "in two short sentences. Then one plain piece of advice, and a calm closing sentence."),
    ("Why your brain/mind does X",
     "Start with 'Your brain/mind often ___' (something people do without noticing). "
     "Then 'That is why ___.' Then 'You don't need to ___.' Give one small, doable action. "
     "End with a sentence about the future or about peace."),
    ("X does not mean Y",
     "Start with '___ does not mean ___.' Then 'You can ___ without ___.' Then "
     "'Some people ___, but they still ___.' End with a calm closing sentence."),
    ("People remember / people often do X",
     "Start with 'People often ___ more than ___.' Then give a simple everyday example in two short "
     "sentences. Then 'So ___.' Then 'You never know ___.' End with a gentle closing sentence."),
]

BANNED = ["journey", "unlock", "embrace", "navigate", "tapestry", "rewire", "whisper",
          "dim your", "in a world", "powerful", "transform", "insights", "resonate",
          "boundaries grow", "speak your truth", "worth is", "vibration"]

def body_of(s):
    ls = strip_header(s.get("lines", []))
    if s.get("cta") and ls and ls[-1] == s["cta"]:
        ls = ls[:-1]
    return ls

def ask(system, user, model=None, temp=0.9, max_tokens=3500, extra=None, soft=False):
    model = model or MODEL
    body = {"model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temp, "max_completion_tokens": max_tokens}
    if "gpt-oss" in model:
        body["reasoning_effort"] = "low"
    if extra:
        body.update(extra)
    for attempt in range(6):
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
            json=body, timeout=120)
        if r.status_code == 429:
            m = re.search(r"try again in ([0-9.]+)s", r.text)
            wait = float(m.group(1)) + 3 if m else 20
            print("Rate limit reached, waiting %.0f seconds..." % wait)
            time.sleep(wait)
            continue
        if r.status_code != 200:
            if soft:
                print("Groq soft error %s: %s" % (r.status_code, r.text[:200]))
                return ""
            raise SystemExit("Groq error %s: %s" % (r.status_code, r.text[:300]))
        return r.json()["choices"][0]["message"].get("content") or ""
    if soft:
        return ""
    raise SystemExit("Groq rate limit kept blocking us, try again in a few minutes")

def get_inspiration(cat):
    """Search the web for what is already going viral. Used only as a feeling guide."""
    angle = random.choice(TOPICS[cat])
    q = ("Search the web for short psychology-fact or dark-psychology quotes about %s "
         "(for example: %s) that people on Reddit, Instagram reels and Pinterest are "
         "sharing and relating to a lot. List 10 of them, one per line, in plain simple "
         "English. No commentary, no numbering, no links." % (CAT_DESC[cat], angle))
    try:
        out = ask("You collect short viral quotes. Output only the lines.", q,
                  model=SEARCH_MODEL, temp=0.3, max_tokens=1200, soft=True,
                  extra={"search_settings": {"include_domains": INSPO_SITES}})
    except Exception as e:
        print("Inspiration search failed:", e)
        return []
    lines = []
    for l in out.replace("\r", "").split("\n"):
        l = tidy(re.sub(r"^[\s\-\*\d\.\)]+", "", l)).strip("\"' ")
        if 25 <= len(l) <= 220 and "http" not in l:
            lines.append(l)
    print("Inspiration for %s: %d lines" % (cat, len(lines)))
    return lines[:12]

def tidy(t):
    t = str(t)
    for a in "\u2010\u2011\u2012":
        t = t.replace(a, "-")
    t = t.replace("\u00a0", " ").replace("\u202f", " ").replace("\u2026", "...")
    return t.strip()

def parse(text):
    t = text.replace("\r", "")
    m = re.search(r"SCRIPT:\s*(.*?)\s*CAPTION:\s*(.*?)\s*(?:HASHTAGS:\s*(.*))?$", t, re.S | re.I)
    if not m:
        raise ValueError("reply did not follow the SCRIPT / CAPTION / HASHTAGS format")
    lines = [tidy(x) for x in m.group(1).split("\n") if tidy(x)]
    caption = tidy(m.group(2).replace("\n", " "))
    tags = tidy((m.group(3) or "").replace("\n", " ")) or \
        "#psychology #mindset #selfgrowth #relationships #mentalstrength"
    return lines, caption, tags

def check(lines, caption, prev_texts, prev_lines, prev_last, insp=()):
    """Return None if the script is fine, else the reason it was rejected."""
    lines = strip_header(lines)
    if not 5 <= len(lines) <= 16:
        return "use 5 to 16 short lines (you used %d)" % len(lines)
    total = len(" ".join(lines).split())
    if not 35 <= total <= 85:
        return "the script must be 35 to 85 words (you used %d)" % total
    for l in lines:
        n = len(l.split())
        if n < 2 or n > 12:
            return "every line must be 2 to 12 words, fix this line: " + l
        if re.search(r"[^\x00-\x7F\u2018\u2019\u201C\u201D\u2013\u2014]", l):
            return "no emojis or special symbols: " + l
        if re.search(r"[A-Za-z]{16,}", l):
            return "use simpler, shorter words in this line: " + l
        if re.search(r"%|\d|studies|research|scientist|proven|according to", l, re.I):
            return "no numbers, statistics or study claims: " + l
        low = l.lower()
        for b in BANNED:
            if b in low:
                return "do not use the cliche word or phrase '%s', say it in plain simple words: %s" % (b, l)
        if len(fold(l).split()) >= 4 and fold(l) in prev_lines:
            return "this line was already used before: " + l
    for l in lines:
        for s in insp:
            if difflib.SequenceMatcher(None, fold(l), s).ratio() > 0.8:
                return "this line is too close to a real quote, write it in your own words: " + l
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

def parse_many(text):
    out = []
    for b in re.split(r"(?im)^\s*#{2,}.*$", text.replace("\r", "")):
        if "SCRIPT:" in b.upper():
            try:
                out.append(parse(b))
            except Exception:
                pass
    return out

def judge(good):
    if len(good) == 1:
        return good[0]
    txt = "\n\n".join("%d)\n%s" % (i + 1, "\n".join(g[0])) for i, g in enumerate(good))
    out = ask("You are a strict editor of viral Instagram psychology reels.",
              "Which script would make a viewer think 'this is exactly about me' and send it to "
              "someone? Prefer a strong first line, one real everyday moment, and a last line that "
              "stays in the heart. Reply with ONLY the number.\n\n" + txt,
              temp=0, max_tokens=800, soft=True)
    m = re.search(r"\d+", out or "")
    if m and 1 <= int(m.group()) <= len(good):
        return good[int(m.group()) - 1]
    return good[0]

def make_one(recent, examples, inspo):
    cat = random.choice(["dark", "brain"])
    topic = pick_topic(cat, recent)
    insp = inspo.get(cat, [])
    insp_fold = [fold(x) for x in insp]

    prev_texts = [fold(" ".join(body_of(s))) for s in recent]
    prev_texts += [fold(e.replace("\n", " ")) for e in examples]
    prev_lines, prev_last = set(), []
    for s in recent:
        ls = body_of(s)
        prev_lines.update(fold(l) for l in ls)
        if ls:
            prev_last.append(fold(ls[-1]))
    for e in examples:
        ls = [l for l in e.split("\n") if l.strip()]
        prev_lines.update(fold(l) for l in ls)
        prev_last.append(fold(ls[-1]))

    shown = random.sample(examples, min(5, len(examples)))
    ex_txt = "\n\n".join("Example %d:\n%s\n%s" % (i + 1, HEADER, e) for i, e in enumerate(shown))
    avoid = [" ".join(body_of(s)[:2]) for s in recent[-40:]]
    pname, pdesc = random.choice(PATTERNS)

    system = ("You write viral Instagram psychology reels in simple English. Your lines make the "
              "viewer feel 'this is exactly me, how did they know?'. You write like a close friend "
              "who says the painful truth gently. No lecture, no filler, no advice dump.")
    base = "Write 5 DIFFERENT scripts. Area: " + CAT_DESC[cat] + ". Starting idea: " + topic + \
           " (you may move to a more specific situation inside this area).\n"
    if insp:
        base += ("\nThese lines are going viral right now. Use them ONLY to feel what makes people "
                 "relate: the tone, the hook, the sting. NEVER copy their words or reuse their exact "
                 "idea:\n" + "\n".join("- " + x for x in insp) + "\n")
    base += ("\nOld examples of our style (do not copy):\n\n" + ex_txt + "\n")
    base += "\nOne script should follow this pattern: " + pname + ". " + pdesc + "\n"
    base += """
WHAT MAKES IT HIT:
- First line is a hook that stops the scroll and speaks to 'you' or to what 'they' do. Never start with 'People often'.
- Show one real, small moment (checking the phone, replying late, sitting quiet in a group, being the one who always calls first). Specific beats general.
- One contrast or twist, like 'They don't miss you, they miss what you did for them.'
- Last line is short and either stings or comforts. It must feel like a truth, not a slogan.
- Be direct and sure of yourself. Use at most one 'sometimes' or 'often'.

RULES:
1. Do NOT write 'Psychology Says:'. Start with the first line after it.
2. 6 to 12 short lines, each 2 to 12 words, 35 to 85 words in total.
3. Simple everyday words. Every line must make clear sense. No poetic fog, no words like peace grows, mind settles, space to breathe.
4. No numbers, no statistics, no 'studies show', no diagnosis, no emojis, no hashtags inside the script.
5. All 5 scripts must have different openings, situations and endings. Never reuse these earlier openings or ideas:
"""
    base += "\n".join("- " + a for a in avoid) if avoid else "- (none yet)"
    base += """

Reply in exactly this format and nothing else:
### 1
SCRIPT:
(lines, one per line)
CAPTION:
(1 to 2 simple sentences ending with a call to save or share)
HASHTAGS:
(5 hashtags)
### 2
... up to ### 5"""

    good, notes = [], []
    for attempt in range(3):
        user = base
        if notes:
            user += "\n\nProblems found in the last batch, avoid them: " + "; ".join(notes[:4])
        cands = parse_many(ask(system, user))
        notes = []
        for lines, caption, tags in cands:
            r = check(lines, caption, prev_texts, prev_lines, prev_last, insp_fold)
            if r:
                notes.append(r)
                print("reject:", r)
            else:
                good.append((lines, caption, tags))
        if good:
            break
    if not good:
        return None
    lines, caption, tags = judge(good)
    cta = random.choice(CTAS[cat])
    return {"category": cat, "topic": topic, "tts": "fish",
            "lines": [HEADER] + strip_header(lines) + [cta],
            "cta": cta, "caption": caption, "hashtags": tags}

def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    examples = load_examples()
    print("Loaded examples:", len(examples))
    inspo = {c: get_inspiration(c) for c in TOPICS}
    for i in range(n):
        if i:
            print("Waiting 25 seconds to stay under the Groq rate limit...")
            time.sleep(25)
        item = make_one(all_scripts(), examples, inspo)
        if not item:
            print("Could not make a good script, skipping")
            continue
        num = "%03d" % next_number()
        os.makedirs("queue/" + num, exist_ok=True)
        with open("queue/%s/script.json" % num, "w", encoding="utf-8") as f:
            json.dump(item, f, ensure_ascii=False, indent=2)
        print("Created queue/" + num, "-", item["topic"])

if __name__ == "__main__":
    main()
