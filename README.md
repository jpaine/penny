# Penny

**Stop overpaying for Claude Code.** Penny runs in your menu bar, watches your usage, and automatically switches to a cheaper model when your task is simple.

No config. No prompts to change. Install and forget.

## How it works

| You type | What Claude would use | What Penny uses | Why |
|----------|----------------------|----------------|-----|
| `claude "fix typo in README"` | Sonnet ($3/M tokens) | Haiku ($0.80/M) | It's a one-word fix |
| `claude "refactor the auth module"` | Sonnet ($3/M) | Sonnet ($3/M) | Complex task, no switch |
| `claude "what does this function do"` | Sonnet ($3/M) | Haiku ($0.80/M) | Simple Q&A |

Over time, Penny learns from your feedback. Reject a switch enough times and it gets more conservative. Accept most and it gets aggressive.

## Install

```bash
curl -sfL https://raw.githubusercontent.com/your-username/penny/main/install.sh | bash
```

Or clone and run locally:

```bash
git clone https://github.com/your-username/penny.git
cd penny
bash install.sh
```

That's it. Start a new terminal and run `claude "hello"` — Penny will print what it saved.

## What you get

| Command | Does |
|---------|------|
| `penny stats` | This week's spend and savings |
| `penny watch` | Live terminal dashboard (refreshing every 5s) |
| `penny set-default` | Permanently switch to the model tier you actually need |
| `penny rate 3 basic` | Correct a classification — trains the classifier |
| `penny health` | Check if everything's working |
| `penny pause` | Stop nudges |
| `penny set-default --restore` | Undo the last default change |

## How it decides

1. **Classifier** (if you've rated 10+ sessions, ≥60% confidence) — Naive Bayes trained on your feedback
2. **Heuristics** (otherwise) — two-tier keyword matching with negation detection
3. **Preference** — if you reject switches >50% of the time, Penny doubles the savings threshold

All thresholds are in `~/.penny/pricing.json` — you can tune them.

## Uninstall

```bash
bash ~/.penny/install.sh --uninstall
```

## Architecture

```
~/.penny/
├── cli.py          # penny CLI commands
├── heuristics.py   # Keyword classification (fallback)
├── learner.py      # Naive Bayes classifier (trained from feedback)
├── preference.py   # Per-user acceptance tracking
├── wrapper.sh      # Intercepts `claude` CLI calls
├── hook.py         # Post-session analytics (Claude Code Stop hook)
├── app.py          # Menu bar app (rumps-based, runs via launchd)
├── costs.py        # Cost estimation from pricing.json
├── util.py         # Atomic JSON I/O
├── pricing.json    # Model prices + thresholds
└── test_penny.py   # 40 tests
```

## Development

```bash
python3 -m pytest test_penny.py -v
```
