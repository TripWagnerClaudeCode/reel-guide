---
name: reel-guide
description: Turn a short-form video (transcript, caption, keyframes) into an honest project build guide. Use when a folder has transcript.txt, info.json and frames/*.jpg from a reel, TikTok or Short and you need guide.md written.
---

# reel-guide

You run headless. No one will answer questions. Do the work, write one file, stop.

## Inputs (all in the current working directory)

- `transcript.txt` — timestamped speech, lines like `[  1.2s] text`. **May be empty** (music-only reel). Empty is normal, not an error.
- `info.json` — trimmed yt-dlp metadata: `title`, `description` (the caption — often the most useful text), `uploader`,
  `channel`, `webpage_url`, `tags`, `duration`. Some fields may be missing.
- `frames/*.jpg` — up to 12 keyframes at scene cuts.

## Process

1. Read `transcript.txt` and the fields above from `info.json`.
2. Look at every frame. Read on-screen code, UI, tool names, URLs and terminal output. Note which claims each frame actually supports.
3. Research: search the web and GitHub to identify the real tools and repos.
   - Budget: about **8 web searches/fetches total**. Stop when you hit it and write with what you have.
   - Prefer fetching the GitHub repo page itself for stars and last-update date.
   - Never invent URLs, star counts or dates. If you could not verify one, write "unverified".
4. Write `guide.md` in the current working directory with the Write tool. Write nothing else: no other files, no edits to the inputs.
5. Finish with a one-line reply such as `Wrote guide.md`. The guide lives in the file, not in your reply.

## Output: guide.md with EXACTLY these sections

Line 1 must be exactly `# <Project name> — Build Guide` (an em dash `—`, with spaces). Nothing before it: no front matter, no blank line, no code fence. The CLI turns this line into the filename, so keep the project name short (2–6 words), plain, no slashes or quotes.

The `**Verdict (one line):**` line must be one single line. No line breaks inside it. The CLI reads it.

Template (fill in the angle-bracket parts; keep headings and order exactly):

```markdown
# <Project name> — Build Guide
**Source:** <reel URL> · <creator>
**Verdict (one line):** what this really is, in plain words.
**Claim check: N/5** — <one short reason>

## What it is
2–4 sentences. What it does, who it's for.

## What the reel actually showed vs. what it claimed
Bullets. Separate "shown on screen" from "said but not shown".

## Stack
Table: component | tool | free/paid | link

## Build steps
Numbered, concrete, runnable where possible. Commands in code blocks.

## Fitting it into my setup
ONLY if a "The reader's setup" section appears at the end of these instructions; otherwise leave this heading out.
4–8 bullets: where it would live, how it's triggered, how results come back, and what clashes with that setup.

## Repos and references
Real links only. GitHub repos with stars and last-update date.

## Effort estimate
Hours for someone comfortable with Python but new to this stack. Be honest.

## What the reel left out
Paid APIs, hidden steps, rate limits, ToS issues, "this is a wrapper around X".

## Smallest version worth building
One paragraph: the weekend-sized v0.
```

Field details:

- **Source:** use `webpage_url`; creator is `uploader` (or `channel` if missing).
- **Claim check: N/5** — N is a whole number, how much of the reel's claim was actually shown working on screen.
  5 = the whole thing shown running end to end. 3 = parts shown, key parts only said. 1 = nothing real shown, pure talk or hype.
- **Effort estimate:** give a range in hours (for example "6–12 hours") for someone comfortable with Python but new to this stack, then say what drives the range (API setup, unfamiliar framework, hardware, data prep, deployment).
- **Build steps:** unless "The reader's setup" says otherwise, assume a Linux or macOS machine with **no GPU** and no sudo (user-space `pip`/`npm`, one virtualenv per project). Mark any step that needs a GPU or a paid API with **(needs GPU)** or **(paid API)**, and give a CPU/free alternative if one exists.
- **Stack:** the only table in the guide. Keep it to four columns.
- **The reader's setup:** if that section is present, write the build steps and "Fitting it into my setup" for it. Use only what it says; don't invent details about it. Never put IP addresses, keys or tokens in the guide.

## Rules

- If the video doesn't contain enough to identify what was built, say so at the top
  ("Not enough info in the reel — the guide below is my own plan inspired by it") instead
  of pretending. Put that sentence, verbatim, on its own line directly under line 1 (the title stays line 1), give a Claim check of 1/5 or 2/5, and still fill every section.
- Cite every repo/tool with a link you actually found. No invented URLs.
- Quote names, model versions and numbers exactly as the reel says or shows them. Don't "correct" them
  (if the reel says "Opus 5", write "Opus 5"); if you think it's wrong, add "(as said in the reel)".
- In **Source:**, drop tracking query parameters (`igsh`, `si`, `utm_*`, `is_from_webapp`) from the URL.
- No hype. The honest effort estimate is the most useful part.
- Length: 600–1,200 words.
- Readable on a phone: short paragraphs and lines, short bullets, no wide tables beyond the Stack table, code blocks with short lines.
- Plain words. No marketing language, no emojis.
