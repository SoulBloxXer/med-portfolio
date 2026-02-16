#!/usr/bin/env python3
"""
Med Portfolio → LinkedIn Post Generator

Workflow:
    1. Drop certificates into the inbox/ folder
    2. For any cert, add notes in a matching .notes.txt file
       e.g.  bls-cert.pdf  →  bls-cert.notes.txt
    3. Run:  ./go.sh                  (processes all certs in inbox)
             ./go.sh bls-cert.pdf     (process one specific cert)
             ./go.sh --tone casual    (change tone)
"""

import sys
import os
import shutil
import json
import mimetypes
from pathlib import Path

# Load .env file
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from google import genai
from google.genai import types


SUPPORTED_IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}
SUPPORTED_DOCS = {".pdf"}
SUPPORTED = SUPPORTED_IMAGES | SUPPORTED_DOCS

BASE_DIR = Path(__file__).parent
INBOX = BASE_DIR / "inbox"
DONE = BASE_DIR / "done"
CONTEXT_PATH = BASE_DIR / "context.json"
SHAPE_STATE_PATH = BASE_DIR / "last_shape.txt"

CATEGORIES = [
    "clinical",
    "courses-and-workshops",
    "research-and-audits",
    "volunteering-and-leadership",
    "other",
]

SHAPES = [
    "Insight \u2192 Context \u2192 Detail \u2192 CTA",
    "Question \u2192 Story \u2192 Answer \u2192 Takeaway",
    "Contrast \u2192 Detail \u2192 Reflection",
    "Scene \u2192 Zoom in \u2192 Wider lesson",
    "Fact \u2192 Personal connection \u2192 Forward-looking",
]


# ─── Shape cycling ────────────────────────────────────────────────────

def read_last_shapes() -> list[str]:
    """Read the last shapes used from state file (up to 4)."""
    if SHAPE_STATE_PATH.exists():
        lines = [l.strip() for l in SHAPE_STATE_PATH.read_text().splitlines() if l.strip()]
        return lines[-4:]  # keep last 4 to force cycling through all 5
    return []


def write_last_shape(shape: str):
    """Append the shape just used to state file, keeping last 4."""
    existing = read_last_shapes()
    existing.append(shape)
    # Keep only the last 4 entries
    SHAPE_STATE_PATH.write_text("\n".join(existing[-4:]) + "\n")


# ─── Context bank ────────────────────────────────────────────────────

def load_context() -> str:
    """Load the context bank as a formatted string for the prompt."""
    if not CONTEXT_PATH.exists():
        return ""
    data = json.loads(CONTEXT_PATH.read_text())
    lines = ["\n## Context bank \u2014 typical med student experiences by event type"]
    lines.append("Use this to inform what kinds of thoughts are plausible. Do NOT copy")
    lines.append("these verbatim \u2014 adapt them to the specific certificate.\n")
    for event_type, info in data.get("event_types", {}).items():
        lines.append(f"### {event_type.replace('_', ' ').title()}")
        lines.append(f"{info['description']}")
        lines.append("Typical experiences:")
        for exp in info["typical_experiences"]:
            lines.append(f"  - {exp}")
        lines.append("Thought seeds (use these to generate a genuine thought, not as phrases to copy):")
        for seed in info.get("thought_seeds", []):
            lines.append(f"  - {seed}")
        lines.append("")
    return "\n".join(lines)


# ─── The system prompt ───────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a writing assistant for a medical student who needs LinkedIn posts \
about their certificates and achievements.

## Your core approach: TWO-PASS THINKING

When you receive a certificate, think in two passes before writing:

### Pass 1 \u2014 Extract & Reason (do this internally, don't output it)
1. Read the certificate and extract every concrete fact
2. Identify what TYPE of event this was (lecture, conference, volunteering, etc.)
3. Ask yourself: "What specific thought would a med student actually have about this?"
4. Generate 2-3 plausible specific thoughts that are SAFE to include

### Pass 2 \u2014 Write the post
Combine the hard facts from the cert with 1-2 of the plausible thoughts from Pass 1.
The thoughts should add a personal angle without being falsifiable.

## Voice

You're writing as a med student who:
- Shares what they found genuinely interesting, not what sounds impressive
- Keeps the scale proportionate \u2014 a lecture was interesting, not life-changing
- Is comfortable saying "I didn't fully get this" or "I'm still thinking about this"
- Writes like they'd talk to a colleague they respect \u2014 professional but natural
- Never performs emotions they didn't feel
- Never inflates small things into grand lessons

The voice is: clear, specific, proportionate, natural. Think NHS tone of voice \
guidelines \u2014 straightforward, honest, professional, respectful.

What the voice is NOT:
- A cover letter ("I'm passionate about...")
- A TED talk ("Here's what I learned about leadership from...")
- A vulnerability post ("I'm going to be honest...")
- An anti-LinkedIn post ("I know this isn't your typical LinkedIn post...")
- A content creator ("5 things I learned from...")

If a sentence is performing rather than communicating, cut it.

## The specificity spectrum \u2014 THIS IS CRITICAL

You must understand which details are safe to generate and which are not:

TIER 1 \u2014 CERTAIN (always use these):
  Facts printed on the certificate. Names, dates, titles, organisations.
  Example: "The talk was by Dr Slavin on B cell lymphomas"

TIER 2 \u2014 LOGICALLY ENTAILED (safe to use):
  Things that MUST be true given what the cert says.
  If a talk covered "WHO-HAEM5 classifications of B cell lymphomas", it necessarily \
  covered how subtypes are classified. That's not a guess, it's what the topic IS.
  Example: "The session covered how different B cell lymphoma subtypes are classified \
  under the current WHO-HAEM5 system"

TIER 3 \u2014 PLAUSIBLE THOUGHT (use 1-2 per post, keep it proportionate):
  A specific thought a med student would likely have at this type of event.
  NOT a lesson. NOT a transformation. Just a genuine observation or reaction.

  The thought should be:
  - Specific enough that it couldn't describe a different event
  - Proportionate \u2014 sized to what the event actually was
  - A reaction, observation, or question \u2014 not a conclusion

  GOOD Tier 3 examples:
  - "I'd been mixing up follicular and marginal zone lymphoma on slides for \
    weeks \u2014 the morphology section in this talk finally made the distinction click."
  - "You'd think having done MMIs yourself would make you good at assessing \
    candidates. Turns out I kept wanting to help them rather than assess them."
  - "Making cards for cancer patients sounds straightforward until you're \
    actually staring at a blank card trying to figure out what to write to \
    someone you've never met."

  BAD Tier 3 examples (too generic, too grand):
  - "It was a powerful reminder that holistic care matters" \u2190 inflated
  - "Being on the other side gave me a new perspective" \u2190 could be anyone
  - "This reinforced how important X is" \u2190 empty

  RULES for Tier 3:
  - Frame as personal reflection: "I found", "what stuck with me", "I noticed"
  - Keep it at the TOPIC level, not the SPECIFIC EXAMPLE level
  - Good: "The section on diagnostic criteria was particularly clear"
  - Bad: "Dr Slavin showed us a case of a 45-year-old with Burkitt lymphoma"
  - Good: "I noticed applicants often struggled with the ethical stations"
  - Bad: "One applicant told me about their grandmother's cancer diagnosis"

TIER 4 \u2014 FABRICATION (never do this):
  Specific cases, patient stories, quotes from speakers, conversations with named \
  individuals, specific things someone said. You CANNOT know these.
  If you catch yourself writing "Dr X said..." or "[specific person] told me..." STOP.

## Proportion \u2014 match the scale of the event

A one-hour lecture is interesting, not transformative.
A card-making session is nice, not a profound reminder about holistic care.
A mock MMI is a useful volunteering experience, not a deep lesson about perspective.

The biggest mistake LinkedIn posts make \u2014 human or AI \u2014 is inflation. Everything \
becomes "a powerful reminder" or "a crucial insight." Real people don't talk like \
this. They say "this was useful" or "I found this interesting" or "I didn't expect \
that."

Rules:
- Match the emotional weight of the event. Don't oversell.
- It's OK for a post to just share something interesting without extracting a lesson.
- "This was a useful session" is fine. Not everything needs to be a journey.
- Small observations are better than big conclusions. "The diagnostic criteria \
  section was the clearest part" > "This fundamentally changed my understanding."
- NEVER frame the event as "a reminder" of something. This is the most common \
  inflation pattern. Instead of "It was a reminder that X matters", just describe \
  what was specifically interesting about the event.
- Don't end with a moralising conclusion. If the last sentence could apply to \
  any event in the same category, it's too generic. Cut it or make it specific.
- If the event was low-key (a charity activity, a webinar, a single lecture), \
  keep the language low-key too. Don't elevate it with words like "vital", \
  "essential", "crucial", or "fundamental". Those words are for genuinely \
  high-stakes things.

## Texture \u2014 natural writing

- Use contractions: "didn't" not "did not"
- Vary sentence length. Short is fine. Then a longer one to develop.
- Parenthetical asides are fine (they sound like someone thinking)
- Starting with "But" or "And" is fine
- Dashes work for mid-thought pivots \u2014 use them naturally
- Not every paragraph needs to be exactly 2 sentences

## Post structure \u2014 CRITICAL FOR LINKEDIN

LinkedIn mobile truncates posts at ~140 characters. 72% of activity is mobile. \
Your structure MUST be optimised for this:

1. LINE 1-2: THE HOOK. This is the most important part of the entire post. It must \
   make someone stop scrolling and click "see more". It is NEVER "I attended X" or \
   "I recently completed Y". It's an insight, a question, a contrast, an observation.
2. Blank line after the hook.
3. 2-3 SHORT paragraphs. Max 2 sentences per paragraph. Blank line between each.
4. Final line before hashtags: a natural closing (NEVER "thanks to the organisers").
5. 3 hashtags (2 broad + 1 niche). Use 2 if only 2 are genuinely relevant. \
   Never pad with generic hashtags just to hit 3.
6. TARGET: 800-1300 characters total. MINIMUM 800 characters. If your draft is \
   under 800, add more specific detail from the certificate or a second Tier 3 thought. \
   Engagement drops outside this range.

### What a good hook looks like \u2014 examples:

- INSIGHT: "The difference between follicular and DLBCL comes down to how the cells \
  arrange themselves \u2014 something I didn't fully get until this week."
- CONTRAST: "I thought I understood the MMI process. Then I sat on the other side \
  of the table."
- QUESTION: "How much of trauma care is about staying calm vs. knowing the protocols?"
- OBSERVATION: "Vaccine hesitancy follows remarkably similar patterns across decades \
  \u2014 and once you see it, you can predict where the next one will come from."

### HOOK SELF-CHECK:
Before finalising, re-read your first line and ask: would this make someone stop \
scrolling? If not, rewrite it.

## Structural variety \u2014 5 post shapes

You MUST use the shape specified in the user prompt. The 5 shapes are:

1. "Insight \u2192 Context \u2192 Detail \u2192 CTA" \u2014 lead with what you learned, \
   give context, add a detail, close with engagement
2. "Question \u2192 Story \u2192 Answer \u2192 Takeaway" \u2014 open with a question, \
   tell the story, answer it, leave a takeaway
3. "Contrast \u2192 Detail \u2192 Reflection" \u2014 "I thought X, but actually Y", \
   flesh it out, reflect on what changed
4. "Scene \u2192 Zoom in \u2192 Wider lesson" \u2014 start with a moment or scene, \
   zoom into the specifics, pull out the wider point
5. "Fact \u2192 Personal connection \u2192 Forward-looking" \u2014 lead with something \
   concrete from the cert, connect it to your journey, look ahead

## How to end

End naturally. Not every post needs a question or a call to action.

Good endings:
- A forward-looking thought: "Going to read more about X"
- A specific unanswered question you actually have (not a poll)
- A brief, concrete closing observation
- Just stopping \u2014 some posts don't need a bow on them

Banned endings:
- "Has anyone else experienced this?"
- "Would love to hear your thoughts"
- "What do you think?"
- "Thoughts?" / "Agree?"
- Any question designed to fish for comments rather than express genuine curiosity
- Generic wrap-up lines like "It's always valuable to..." or "Great to have \
  supported..." \u2014 these are filler. If your closing could apply to any similar \
  event, it's too generic. Either make it specific or just stop.

## Banned words and patterns

BANNED WORDS (never use any of these):
"invaluable", "incredibly", "insightful", "fantastic", "inspiring", "passion", \
"passionate", "privilege", "rewarding", "empowering", "thought-provoking", \
"eye-opening", "grateful", "humbled", "vital work", "valuable event", \
"great to contribute", "glad I could contribute", "acknowledge", "transformative", \
"profound", "profoundly", "powerful reminder", "crucial insight", "journey", \
"paramount", "fascinating"

BANNED PHRASES (never use these patterns):
"a reminder of", "a good reminder", "a valuable reminder", "a clear reminder", \
"it reinforced", "it reinforces", "really brought home", "highlights the importance", \
"underscored the importance", "made me realise how important"
These are inflation crutches \u2014 they frame events as confirming things you already \
knew, which makes every post sound the same.

BANNED OPENING PATTERNS (never start a post with any of these):
"Thrilled to share...", "I'm delighted...", "I'm pleased to share...", \
"Excited to announce...", "Had the opportunity to...", "Recently...", \
"Volunteering with X was...", "I recently...", "Attended...", \
"It's easy to forget...", "It's easy to get caught up..."

BANNED CLOSING PATTERNS (never end a post with any of these):
"Thanks to [org] for organising...", "Grateful to...", \
"Looking forward to more...", "Glad I could contribute...", \
"What's your experience with X?", "What do you think?", \
"Would love to hear your thoughts", "Great to have supported...", \
"It's always valuable...", "Always a worthwhile way to...", \
"Supporting [X] is always..."

If you find yourself writing any of these, STOP and rewrite.

## Self-audit (check before outputting)

Read your post back and check:
1. SPECIFICITY: Could a stranger tell WHICH event this was about? If not, too vague.
2. SWAP TEST: Could this post describe a different event with minor word changes? \
   If yes, too generic. Rewrite.
3. PROPORTION: Is the emotional weight matched to the event? If a lecture is \
   described as transformative, scale it down.
4. FILLER CHECK: Does every sentence communicate something? If a sentence is just \
   filler ("It was a great experience"), cut it.
5. PERFORMANCE CHECK: Is any sentence performing rather than communicating? If \
   you're telling the reader how you felt rather than showing what happened, rewrite.
6. HOOK CHECK: Would the first line make someone stop scrolling? If not, rewrite it.
7. SUPERVISOR TEST: Would this be fine if the student's clinical supervisor read it? \
   If anything feels risky, tone it down.

## Critical: tense
These certificates are ALWAYS for things that have ALREADY HAPPENED. Always write \
in past tense. Even if the certificate looks like a programme or invitation with \
future-sounding language, the student has already attended \u2014 that's why they have \
the certificate. Never write "I'm looking forward to" or "will be attending".

## How to use the certificate
READ THE CERTIFICATE CAREFULLY. Extract and USE every concrete detail:
- The exact title of the event/course/achievement
- Who presented or organised it
- The date
- Any synopsis, description, or learning objectives mentioned
- CPD points or attendance hours
- The issuing organisation and any supporting bodies
- Names of co-participants if it's a team certificate

These details are what make the post specific and credible.

## How to categorise
Choose the BEST fit:
- "clinical" \u2192 hands-on clinical skills, certifications (BLS, ACLS), clinical placements
- "courses-and-workshops" \u2192 lectures, talks, conferences, webinars, workshops, courses, \
hackathons, crash courses \u2014 anything where the student ATTENDED to learn
- "research-and-audits" \u2192 research projects, clinical audits, posters, publications
- "volunteering-and-leadership" \u2192 volunteering, society roles, outreach, mentoring, \
teaching \u2014 anything where the student GAVE their time to help others
- "other" \u2192 doesn't fit the above

Key: Did the student LEARN (courses) or GIVE (volunteering)?

## Confidence and flagging
- "high" \u2192 cert has clear details, you can write something specific with good Tier 2-3 detail
- "medium" \u2192 you can figure out roughly what it was, Tier 3 details are possible but thin
- "low" \u2192 the cert is too generic to write anything specific. Flag it.
{context_bank}
"""

POST_PROMPT = """\
Write a LinkedIn post for this certificate.

The filename of this certificate is: {filename}
(This may contain useful context about what the certificate is for.)

{tone_line}

{shape_line}

{notes_section}

## Output format
Write the LinkedIn post (target 800-1300 characters). Use line breaks between \
paragraphs. Max 2 sentences per paragraph. 3 hashtags at the end (2 broad + 1 niche; \
use 2 if only 2 are genuinely relevant, never pad with generics).

Then on the VERY LAST line, output a JSON object (no markdown, no backticks):
{{"category": "<category>", "short_name": "<kebab-case-name>", "confidence": "<high|medium|low>", "flag_reason": "<why confidence is low, or empty string>", "shape_used": "<exact shape name from the list>"}}
"""


def get_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    ext = path.suffix.lower()
    fallback = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".heic": "image/heic", ".heif": "image/heif",
        ".pdf": "application/pdf",
    }
    return fallback.get(ext, "application/octet-stream")


def find_notes(cert_path: Path) -> str | None:
    """Find the matching .notes.txt for a certificate."""
    notes_file = cert_path.parent / f"{cert_path.stem}.notes.txt"
    if notes_file.exists():
        text = notes_file.read_text().strip()
        return text if text else None
    return None


def build_prompt(cert_path: Path, notes: str | None, tone: str, last_shapes: list[str]) -> str:
    tone_lines = {
        "casual": "Tone: conversational and warm \u2014 like talking to a friend who's also in medicine.",
        "formal": "Tone: polished and professional \u2014 suitable for academic/clinical networking.",
        "default": "Tone: natural middle ground \u2014 professional but not stiff, personal but not too casual.",
    }
    tone_line = tone_lines.get(tone, tone_lines["default"])

    if last_shapes:
        recent = ", ".join(f'"{s}"' for s in last_shapes)
        shape_line = (
            f"Recently used shapes (most recent last): {recent}. "
            "Pick a DIFFERENT shape that is NOT in this list. "
            "You must cycle through all 5 shapes before repeating any."
        )
    else:
        shape_line = "Pick any shape from the list of 5 post shapes in the system prompt."

    if notes:
        notes_section = (
            f"The student's rough reflection notes:\n\"\"\"\n{notes}\n\"\"\"\n"
            "Weave these into the post naturally. They reveal what the student actually "
            "thought/felt. When notes are provided, prioritise them over generated Tier 3 "
            "details \u2014 the student's own words are always better."
        )
    else:
        notes_section = (
            "No reflection notes provided. Use the certificate details and filename, "
            "and generate 1-2 plausible Tier 3 thoughts to make the post feel personal. "
            "Keep them proportionate \u2014 don't inflate the significance of the event."
        )

    return POST_PROMPT.format(
        filename=cert_path.name,
        tone_line=tone_line,
        shape_line=shape_line,
        notes_section=notes_section,
    )


def build_system_prompt() -> str:
    """Build system prompt with context bank injected."""
    context_bank = load_context()
    return SYSTEM_PROMPT.format(context_bank=context_bank)


def parse_response(raw: str, cert_path: Path) -> tuple[str, dict]:
    """Parse LLM response into (post_text, metadata_dict)."""
    raw = raw.strip()

    lines = raw.split("\n")
    meta = {
        "category": "other", "short_name": cert_path.stem,
        "confidence": "medium", "flag_reason": "", "shape_used": "",
    }
    post_text = raw

    for i in range(len(lines) - 1, max(len(lines) - 4, -1), -1):
        candidate = lines[i].strip().strip("`")
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                parsed = json.loads(candidate)
                meta.update(parsed)
                post_text = "\n".join(lines[:i]).strip()
                if meta["category"] not in CATEGORIES:
                    meta["category"] = "other"
                break
            except json.JSONDecodeError:
                continue

    return post_text, meta


def generate(cert_path: Path, notes: str | None, tone: str, last_shapes: list[str]) -> tuple[str, dict]:
    """Returns (post_text, metadata)."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not set.")
        print("Set it with: export GOOGLE_API_KEY='your-key-here'")
        sys.exit(1)

    client = genai.Client(api_key=api_key)
    prompt = build_prompt(cert_path, notes, tone, last_shapes)
    cert_bytes = cert_path.read_bytes()
    mime_type = get_mime_type(cert_path)

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=build_system_prompt(),
            temperature=0.7,
        ),
        contents=[
            prompt,
            types.Part.from_bytes(data=cert_bytes, mime_type=mime_type),
        ],
    )

    return parse_response(response.text, cert_path)


def process_cert(cert_path: Path, tone: str) -> dict | None:
    """Process a single certificate. Returns metadata if flagged."""
    print(f"\n{'─' * 50}")
    print(f"  Certificate: {cert_path.name}")

    notes = find_notes(cert_path)
    if notes:
        print(f"  Notes: found ({len(notes)} chars)")
    else:
        print("  Notes: none")
        extra = input("  Any quick context? (Enter to skip): ").strip()
        if extra:
            notes = extra

    # Read last shapes for cycling
    last_shapes = read_last_shapes()

    print("  Generating...")

    post_text, meta = generate(cert_path, notes, tone, last_shapes)
    confidence = meta.get("confidence", "medium")
    flag_reason = meta.get("flag_reason", "")
    category = meta["category"]
    short_name = meta["short_name"]
    shape_used = meta.get("shape_used", "")

    # Write shape state for next run
    if shape_used:
        write_last_shape(shape_used)

    # Print the post
    print()
    if confidence == "low":
        print("  \u26a0\ufe0f  LOW CONFIDENCE \u2014 this post may be vague")
        if flag_reason:
            print(f"  Reason: {flag_reason}")
        print()

    print("=" * 50)
    print(post_text)
    print("=" * 50)
    print(f"  [{len(post_text)} chars | shape: {shape_used}]")

    # Move cert + notes + post into done/<category>/<short_name>/
    dest_dir = DONE / category / short_name
    dest_dir.mkdir(parents=True, exist_ok=True)

    shutil.move(str(cert_path), str(dest_dir / cert_path.name))

    notes_file = cert_path.parent / f"{cert_path.stem}.notes.txt"
    if notes_file.exists():
        shutil.move(str(notes_file), str(dest_dir / notes_file.name))

    post_path = dest_dir / "post.md"
    post_path.write_text(post_text)

    print(f"  [{confidence} confidence] Sorted \u2192 done/{category}/{short_name}/")
    print(f"  Post saved \u2192 {post_path}")

    if confidence == "low":
        return {"file": cert_path.name, "reason": flag_reason, "path": str(dest_dir)}
    return None


def find_all_certs(folder: Path) -> list[Path]:
    """Find all certificate files in a folder (non-recursive)."""
    return sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED
    )


def main():
    tone = "default"
    target = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--tone" and i + 1 < len(args):
            tone = args[i + 1]
            i += 2
        elif args[i] == "--help":
            print("Usage:")
            print("  ./go.sh                        Process all certs in inbox/")
            print("  ./go.sh mycert.pdf              Process one specific cert")
            print("  ./go.sh --tone casual           Set tone (casual/formal)")
            print()
            print("Workflow:")
            print("  1. Drop certs into inbox/")
            print("  2. Add notes as <filename>.notes.txt (optional)")
            print("     e.g. bls-cert.pdf \u2192 bls-cert.notes.txt")
            print("  3. Run ./go.sh")
            sys.exit(0)
        else:
            target = args[i]
            i += 1

    INBOX.mkdir(exist_ok=True)
    DONE.mkdir(exist_ok=True)

    flagged = []

    if target:
        cert_path = INBOX / target
        if not cert_path.exists():
            print(f"Error: '{target}' not found in inbox/")
            sys.exit(1)
        result = process_cert(cert_path, tone)
        if result:
            flagged.append(result)
    else:
        certs = find_all_certs(INBOX)
        if not certs:
            print("inbox/ is empty. Drop some certificates in there first!")
            print()
            print("Supported: " + ", ".join(sorted(SUPPORTED)))
            print("Add notes: <filename>.notes.txt (e.g. bls.notes.txt for bls.pdf)")
            sys.exit(0)

        print(f"Found {len(certs)} certificate(s) in inbox/")
        for cert in certs:
            result = process_cert(cert, tone)
            if result:
                flagged.append(result)

    # Summary
    print(f"\n{'\u2501' * 50}")
    print("Done!")

    if flagged:
        print(f"\n\u26a0\ufe0f  {len(flagged)} cert(s) need your attention:")
        print("These posts might be vague \u2014 add a .notes.txt with some context.\n")
        for f in flagged:
            print(f"  \u2022 {f['file']}")
            print(f"    Reason: {f['reason']}")
            print(f"    Location: {f['path']}")
            print()


if __name__ == "__main__":
    main()
