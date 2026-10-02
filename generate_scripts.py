import json, os, sys, re, glob, random, difflib, time
import requests

KEY = os.environ["GROQ_API_KEY"]
MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"
SEARCH_MODEL = os.environ.get("GROQ_SEARCH_MODEL") or "groq/compound-mini"
HEADERS = {"dark": "Psychology Says:", "brain": "Buddha Wisdom:"}
HEADER_STARTS = ("psychology says", "buddha wisdom")
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
        "anger when someone insults you", "holding on to people who left",
        "overthinking what others think of you", "expecting people to treat you the way you treat them",
        "the pain of being betrayed", "jealousy of others' success",
        "loneliness even in a crowd", "letting go of the past",
        "worrying about a future that may never come", "wanting more and never feeling enough",
        "ego and needing to be right", "fear of losing someone",
        "being hurt by words", "comparing your life with others",
        "patience when life is slow", "forgiving someone who never said sorry",
        "pain that you keep adding to yourself", "being kind to people who are not kind to you",
        "peace through silence", "attachment to things and people",
        "regret about wasted time", "when good people get treated badly",
        "feeling like you are not enough", "burnout and doing too much",
        "starting again after failure",
    ],
}

CAT_DESC = {
    "dark": "relationships, people, boundaries and self-respect",
    "brain": "Buddha wisdom and Zen parables applied to real life problems (anger, attachment, overthinking, letting go)",
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
        if fold(b.split("\n")[0]).startswith(HEADER_STARTS):
            b = "\n".join(b.split("\n")[1:]).strip()
        if b:
            out.append(b)
    return out

def strip_header(lines):
    if lines and fold(lines[0]).startswith(HEADER_STARTS):
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
        "Follow for more daily Buddha wisdom for real life.",
        "Follow for more daily life changing wisdom.",
        "Follow if this touched your heart.",
        "Follow for more daily videos that heal the mind.",
    ],
}

PATTERNS = {
    "brain": [
        ("A man asks Buddha, Buddha answers with a simple image",
         "Open with a real life problem: 'A man asked Buddha, why ___?' Buddha answers by doing or showing "
         "one simple thing (a cup, a stone, an arrow, salt in water). End by telling 'you' the lesson in one line."),
        ("Classic parable retold for modern life",
         "Retell a short, classic Buddhist or Zen parable in your own words (2 or 3 plain steps) and end by "
         "connecting it to a modern problem like texting, work or family. Last line is the lesson for 'you'."),
        ("A monk and one hard truth",
         "Open with 'A monk was asked ___.' He gives a short, surprising answer. Then one line on what this "
         "means in your daily life. Last line stays in the heart."),
    ],
    "dark": [
        ("Mini story: a person, a pattern, the dark truth",
         "Tell a 3 to 4 line story about one person (a girl, a boy, a friend) stuck in a real pattern. Then "
         "one line of dark psychology that explains why people do this. Last line is a truth for 'you'."),
        ("You-direct truth with one real moment",
         "Open with a thing 'you' do. Show one everyday moment using 'you' or 'they'. Explain the psychology "
         "in one plain line ('Your brain...', 'That is why...'). Add one twist. End with a line that stings or comforts."),
        ("What they really mean",
         "Open with 'When someone ___, they usually ___.' Give the hidden reason in simple words, then what "
         "'you' should notice, and a last line that stays in the heart."),
    ],
}

BANNED = ["journey", "unlock", "embrace", "navigate", "tapestry", "rewire", "whisper",
          "dim your", "in a world", "powerful", "transform", "insights", "resonate",
          "boundaries grow", "speak your truth", "worth is", "vibration",
          "peace", "space to breathe", "heart becomes", "quiet act", "honor your", "gentle", "mind settles", "kindest", "inner child", "higher self", "universe"]

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

SUBS = {
    "dark": ["DarkPsychology101", "psychologyfacts", "PsychologicalTricks"],
    "brain": ["Buddhism", "zen", "Stoicism"],
}

def reddit_lines(cat):
    """Best effort: top posts of the week from public subreddits. Silently skipped if blocked."""
    out = []
    for sub in SUBS[cat]:
        try:
            r = requests.get("https://www.reddit.com/r/%s/top.json?t=week&limit=30" % sub,
                             headers={"User-Agent": "reel-bot/1.0 (personal project)"}, timeout=20)
            if r.status_code != 200:
                print("reddit %s: status %s (skipped)" % (sub, r.status_code))
                continue
            for c in r.json()["data"]["children"]:
                t = tidy(c["data"].get("title", ""))
                if 30 <= len(t) <= 170 and "?" not in t and "http" not in t \
                        and not re.match(r"(?i)^(i |my |aita|am i|how |why |what )", t):
                    out.append(t)
        except Exception as e:
            print("reddit %s failed: %s" % (sub, e))
    print("Reddit lines for %s: %d" % (cat, len(out)))
    return out

def local_bank():
    """Lines you paste yourself into style/viral.txt (one per line, # = comment)."""
    p = "style/viral.txt"
    if not os.path.exists(p):
        return []
    return [tidy(l) for l in open(p, encoding="utf-8").read().split("\n")
            if l.strip() and not l.strip().startswith("#")]

SEARCH_ASK = {
    "dark": ("Search the web for the MOST VIRAL short dark psychology quotes, facts and mini stories about "
             "%s (for example: %s) that people are sharing on Instagram reels, Pinterest, Reddit and Quora. "
             "List 10, one per line, in plain simple English. For a mini story give it in one line. "
             "No commentary, no numbering, no links."),
    "brain": ("Search the web for the MOST VIRAL Buddha stories, Zen parables and Buddha wisdom quotes about "
              "%s (for example: %s) that people are sharing on Instagram reels, Pinterest, Reddit and Quora. "
              "List 10, one per line, in plain simple English. For a story give the whole story in one line "
              "(who asked what, what the answer was, the lesson). No commentary, no numbering, no links."),
}

def get_inspiration(cat):
    """Collect what is already going viral. Used only as a feeling guide, never copied."""
    lines = reddit_lines(cat) + local_bank()
    angle = random.choice(TOPICS[cat])
    for dom in (INSPO_SITES, None):
        q = SEARCH_ASK[cat] % (CAT_DESC[cat], angle)
        extra = {"search_settings": {"include_domains": dom}} if dom else None
        try:
            out = ask("You collect short viral quotes and stories. Output only the lines.", q,
                      model=SEARCH_MODEL, temp=0.3, max_tokens=1500, soft=True, extra=extra)
        except BaseException as e:
            print("Inspiration search failed:", e)
            continue
        got = 0
        for l in out.replace("\r", "").split("\n"):
            l = tidy(re.sub(r"^[\s\-\*\d\.\)]+", "", l)).strip("\"' ")
            if 25 <= len(l) <= 320 and "http" not in l:
                lines.append(l)
                got += 1
        print("Web search (%s) gave %d lines" % ("sites" if dom else "open web", got))
        if got >= 5:
            break
    random.shuffle(lines)
    print("Inspiration for %s: %d lines" % (cat, len(lines)))
    return lines[:14]

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
    if not 6 <= len(lines) <= 18:
        return "use 6 to 18 short lines (you used %d)" % len(lines)
    total = len(" ".join(lines).split())
    if not 45 <= total <= 105:
        return "the script must be 45 to 105 words (you used %d)" % total
    for l in lines:
        n = len(l.split())
        if n < 2 or n > 14:
            return "every line must be 2 to 14 words, fix this line: " + l
        if re.search(r"[^\x00-\x7F\u2018\u2019\u201C\u201D\u2013\u2014]", l):
            return "no emojis or special symbols: " + l
        if re.search(r"[A-Za-z]{16,}", l):
            return "use simpler, shorter words in this line: " + l
        if re.search(r"%|\d|studies|research|scientist|proven|according to", l, re.I):
            return "no numbers, statistics or study claims: " + l
        if re.search(r"(?<![A-Za-z])I(?![a-z])", l) or re.search(r"\b(we|our|us)\b", l, re.I):
            return "never write as 'I' or 'we'. Tell a story about someone, or talk to 'you'. Fix: " + l
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
    if not re.search(r"\b(you|your|you're|you've)\b", " ".join(lines[-3:]), re.I):
        return "the last 3 lines must speak to 'you' so the viewer feels it is about them"
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

def polish(lines, caption, prev_texts, prev_lines, prev_last, insp_fold):
    """One cheap rewrite: make vague lines concrete. Keeps the old version if the rewrite fails the checks."""
    out = ask("You are a sharp editor of viral Instagram psychology reels.",
              "Rewrite this script so it hits harder. Replace every vague or poetic line with a "
              "plain, concrete one a real person would say or feel. Keep the same idea and story, the same "
              "number of lines (+/- 1), each line 2 to 14 words, simple English, no numbers, no "
              "cliches, never write as 'I' or 'we'. Keep every line connected to the previous one and the last lines speaking to 'you'. The last line must sting or comfort. Reply with ONLY the lines, one per "
              "line.\n\n" + "\n".join(lines), temp=0.6, max_tokens=600, soft=True)
    new = [tidy(re.sub(r"^[\s\-\*\d\.\)]+", "", x)) for x in out.replace("\r", "").split("\n") if tidy(x)]
    if new and check(new, caption, prev_texts, prev_lines, prev_last, insp_fold) is None:
        return new
    return lines

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

    HEADER = HEADERS[cat]
    shown = random.sample(examples, min(4, len(examples))) if cat == "dark" else []
    ex_txt = "\n\n".join("Example %d:\n%s\n%s" % (i + 1, HEADERS["dark"], e) for i, e in enumerate(shown))
    avoid = [" ".join(body_of(s)[:2]) for s in recent[-40:]]
    pname, pdesc = random.choice(PATTERNS[cat])

    if cat == "brain":
        system = ("You write viral Instagram reels of Buddha wisdom and Zen stories in very simple English. "
                  "Each reel is a short story or parable that touches a real life problem, and ends with a "
                  "lesson that makes the viewer feel 'this is about me'. Warm, calm, direct. "
                  "Never invent fake Buddha quotes: tell it as a story ('A man asked Buddha...') and keep it plain.")
    else:
        system = ("You write viral Instagram dark psychology reels in simple English. Each reel is a short "
                  "story or a sharp truth about real relationship and life problems that makes the viewer "
                  "feel 'this is exactly me, how did they know?'. Like a close friend who says the painful "
                  "truth. No lecture, no filler.")
    base = "Write 5 DIFFERENT scripts. Area: " + CAT_DESC[cat] + ". Starting idea: " + topic + \
           " (you may move to a more specific situation inside this area).\n"
    if insp:
        base += ("\nThese lines are going viral right now. Use them ONLY to feel what makes people "
                 "relate: the tone, the hook, the sting. NEVER copy their words or reuse their exact "
                 "idea:\n" + "\n".join("- " + x for x in insp) + "\n")
    if ex_txt:
        base += ("\nOld examples of our style (do not copy):\n\n" + ex_txt + "\n")
    base += "\nOne script should follow this pattern: " + pname + ". " + pdesc + "\n"
    base += """
WHAT MAKES IT HIT:
1. HOOK (first line): a real life problem or question that stops the scroll. Example feel: 'A man asked Buddha, why do people hurt me?' or 'You keep chasing people who never chase you.'
2. STORY or MOMENT (3 to 5 lines): simple, one clear image or scene. No random details.
3. TURN (1 to 2 lines): the answer or the hidden truth, the line people will screenshot.
4. LAST LINES: speak to 'you'. The final line is short and either stings or comforts, a truth and not a slogan.
- Every line follows the one before. Plain everyday words a 12 year old understands.

RULES:
1. Do NOT write 'Psychology Says:'. Start with the first line after it.
2. 8 to 14 short lines, each 2 to 14 words, 55 to 100 words in total.
3. Simple everyday words. Every line must make clear sense. No poetic fog. Never write as 'I' or 'we'.
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
    lines = polish(lines, caption, prev_texts, prev_lines, prev_last, insp_fold)
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
