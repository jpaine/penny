# Penny

**Stop overpaying for Claude Code.** Penny runs in your menu bar, watches your usage, and automatically switches to a cheaper model when your task is simple.

No config. No prompts to change. Install and forget.

## Install

**Prerequisites:** Python 3, `pip`, and [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) installed.

```bash
curl -sfL https://raw.githubusercontent.com/jpaine/penny/main/install.sh | bash
```

Or clone and run locally:

```bash
git clone https://github.com/jpaine/penny.git
cd penny
bash install.sh
```

**What install does:**
- Copies files to `~/.penny/`
- Adds `~/.penny` to your `PATH` (so Penny intercepts `claude` calls)
- Installs Python dependencies (`rumps` for menu bar, `rich` for dashboard)
- Launches the menu bar app (via launchd)
- Installs a post-session hook (tracks usage after each Claude Code session)

**Verify it's working:**
```bash
# Open a new terminal, then:
penny health
claude "explain what this function does" -- say
# You should see: "Penny: using faster mode (~$0.03 saved)"
```

First time? Run `claude "hello"` — you'll see a welcome message.

## How it works

| You type | Default model | Penny uses | Why |
|----------|---------------|------------|-----|
| `claude "fix typo in README"` | Sonnet ($3/M tokens) | Haiku ($0.80/M) | Simple edit |
| `claude "refactor the auth module"` | Sonnet ($3/M) | Sonnet ($3/M) | Complex task, skip |
| `claude "what does this function do"` | Sonnet ($3/M) | Haiku ($0.80/M) | Quick question |
| `claude` (interactive, no prompt) | Sonnet ($3/M) | Sonnet ($3/M) | Interactive, skip |

Interactive sessions are never switched — only one-shot prompts (`claude "..."`) get evaluated.

## Commands

| Command | What it does |
|---------|-------------|
| `penny stats` | Show weekly spend and savings |
| `penny watch` | Live dashboard (refreshes every 5s) |
| `penny set-default` | Switch your default model permanently |
| `penny set-default --restore` | Undo the last default change |
| `penny rate` | List recent classifications you can correct |
| `penny rate-session 42 basic` | Correct session #42 to "basic" |
| `penny pause` / `penny resume` | Turn nudges on/off |
| `penny health` | Check Penny's status, error log, hook freshness |
| `penny help` | Show all commands |

## Teaching Penny

The classifier gets better the more you correct it. After 10+ corrections, Penny uses the trained model instead of keyword heuristics.

```bash
# List your recent sessions
penny rate
# Existing feedback entries: 3
#
#   [42] Mon 14:22   standard   explain what this function does
#   [43] Tue 09:15   advanced   refactor the auth module
#   [44] Tue 10:30     basic   add a docstring
#
# To rate: penny rate-session <index> <basic|standard|advanced>
# Example: penny rate-session 42 basic

# Correct session 42 — it was simple, should be "basic"
penny rate-session 42 basic
# Saved feedback: 'explain what this function does'... → basic
```

After enough corrections, Penny will start overriding its own guesses with learned ones. You can always check which system is driving decisions in `penny watch`.

## Menu bar

The menu bar app runs automatically (via launchd). It shows your weekly spend. Click it to see:

- `$3.20 this week` — total spent
- `You could save: $0.80` — missed savings on overpaid sessions
- `penny set-default` — shortcut (appears after 3+ overpaid sessions)

It'll also pop a macOS notification when a session could've been cheaper.

## How it decides

1. **Learned classifier** (≥10 rated sessions, ≥60% confidence) — Multinomial Naive Bayes trained on your corrections
2. **Keyword heuristics** (fallback) — two-tier rules with negation detection
3. **Preference adjustment** — if you reject switches >50% of the time, Penny doubles the savings bar

All configurable in `~/.penny/pricing.json`.

## Uninstall

```bash
bash ~/.penny/install.sh --uninstall
```

This removes the PATH entry, unloads the menu bar, removes the hook, and deletes `~/.penny/`. You'll need to open a new terminal for the PATH change to take effect.

## Troubleshooting

| Problem | Check |
|---------|-------|
| Penny never switches | Run `penny health`. If "hook not firing", your Claude Code version may not support stop hooks — check `~/.claude/settings.json` |
| `penny` command not found | Open a new terminal or `source ~/.bash_profile` |
| "I switched to a better model and Penny kept it on Haiku" | Use `--model` flag explicitly, e.g. `claude "..." --model claude-sonnet-5` — next time Penny will learn that this prompt type prefers sonnet |
| No menu bar icon | Run `launchctl list | grep penny` — if not listed, re-run install |
| Rates are wrong | Edit `~/.penny/pricing.json` directly (model prices, thresholds, caps) |

## Development

```bash
pytest test_penny.py -v
```

## Architecture

```
~/.penny/
├── cli.py          # Commands (stats, watch, health, rate, etc.)
├── heuristics.py   # Keyword classification (fallback + self-tests)
├── learner.py      # Naive Bayes classifier (from rated feedback)
├── preference.py   # Per-user acceptance tracking
├── wrapper.sh      # Intercepts `claude` calls, decides model switch
├── hook.py         # Post-session analytics (Claude Code stop hook)
├── app.py          # macOS menu bar (rumps + launchd)
├── costs.py        # Cost estimation from pricing.json
├── util.py         # Atomic JSON read/write with file locking
├── pricing.json    # Model prices + configurable thresholds
└── test_penny.py   # Pytest suite
```
