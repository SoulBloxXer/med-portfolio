# Med Portfolio — Operational Notes

Cert-to-LinkedIn-post generator for a med student. Drop certs in `inbox/`, run `./go.sh`, get posts in `done/`.

## Key Files
- `generate.py` — everything: SYSTEM_PROMPT, LLM calls, file handling, shape cycling, parsing
- `context.json` — event-type-specific `typical_experiences` and `thought_seeds`
- `last_shape.txt` — tracks last 4 shapes used (cycling state)
- `.env` — `GOOGLE_API_KEY` (Gemini 2.5 Pro)

## How to Audit a Run
```bash
# Banned words (target: 0)
grep -riE 'invaluable|incredibly|insightful|fantastic|inspiring|passion[^s]|passionate|privilege|rewarding|empowering|thought-provoking|eye-opening|grateful|humbled|transformative|profound|journey|paramount|fascinating' done/*/post.md done/*/*/post.md

# Banned phrases — the "reminder" family (target: 0)
grep -riE 'a reminder|a good reminder|a valuable reminder|it reinforced|it reinforces|really brought home|highlights the importance' done/*/post.md done/*/*/post.md

# Banned openings (target: 0)
grep -riE "^(Thrilled|I'm delighted|I'm pleased|Excited to|Had the opportunity|Recently|I recently|Attended|It's easy to forget|It's easy to get caught)" done/*/post.md done/*/*/post.md

# Banned closings — check last non-hashtag line of each post
grep -riE 'Looking forward to|Grateful to|Glad I could|What.s your experience|Great to have supported|It.s always valuable|Always a worthwhile' done/*/post.md done/*/*/post.md

# Character counts (target: all 800-1300)
for f in $(find done -name "post.md" | sort); do echo "$(wc -c < "$f" | tr -d ' ') - $(basename $(dirname "$f"))"; done

# Shape cycling (target: all 5 shapes appear)
cat last_shape.txt
```

## Lessons Learned (update this as new patterns surface)

1. **Banned words are whack-a-mole.** The self-audit instruction in the system prompt is the primary quality gate. The banned list is a backstop that catches the obvious ones. New words will always leak — add them when they do, but don't rely on the list alone.

2. **"Reminder" was the #1 inflation pattern.** 6/10 posts used "a reminder of how important X is" in the first v5 run. Banning the entire "reminder" family of phrases fixed it completely. Watch for new inflation crutches emerging.

3. **Shape cycling needs 4-deep history, not 1.** When `last_shape.txt` only tracked the last shape, the LLM ping-ponged between 2 shapes. Tracking the last 4 forces it to cycle through all 5 before repeating.

4. **The LLM model and its prompts are rarely the problem.** When output quality is off, look at the pipeline code first — shape cycling logic, context bank content, banned word lists, `load_context()` parsing. The SYSTEM_PROMPT is mature; the infrastructure around it is where bugs hide.

5. **"Performative authenticity" is as cringe as "performative professionalism."** The user explicitly flagged this: LinkedIn has always been full of NPC-style posts, and over-correcting into edgy/casual/anti-LinkedIn voice is just a different kind of performance. The sweet spot is "quietly genuine" — substance-led, proportionate, no performance in either direction.

6. **Proportion > opinion.** An early plan pushed for "have opinions" and "rough edges." For a med student, this carries GMC risk. The better instruction is "match the scale of the event" — a lecture is interesting, not transformative.

7. **New cliches form fast.** Any pattern the LLM latches onto will appear in 4+ of 10 posts. After banning old cliches, "It's easy to forget..." immediately became the new one. Monitor for clustering after every batch run.

8. **Closings are the hardest part.** The LLM defaults to performative wrap-ups ("Great to have supported...", "It's always valuable...") and "Looking forward to..." even when explicitly banned. These need to be banned AND the "How to end" section needs positive examples. Organic endings ("Going to read more about X", or just stopping) are better.

9. **"Looking forward to" is persistent.** Even after being added to banned closings, it still leaks. The LLM treats it as a natural forward-looking ending and ignores the ban. May need stronger language or an additional self-audit check specifically for this.

10. **Categorisation can drift.** Hackathons should be `courses-and-workshops` per the categorisation guidance, but the LLM occasionally puts them in `other`. The guidance says "hackathons" explicitly — if it drifts, check the categorisation section wording.

11. **Diminishing returns are real.** After 3 audit-fix cycles in v5, violations dropped from ~12 to ~3. The remaining leaks (1 banned word, 2 banned closings per batch of 10) are at the noise floor of what prompt engineering can achieve with Flash.

12. **Model upgrade beats validation code.** When the prompt is mature but the model still ignores instructions ~3 times per batch, the fix is a heavier model (Flash → Pro), not post-generation validation code in Python. The user correctly identified this as overengineering — the prompt already says what to do, you just need a model that listens better.
