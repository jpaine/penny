#!/bin/bash
# Penny wrapper around the `claude` CLI. Auto-switches to a cheaper model
# for simple one-shot prompts and otherwise stays completely silent.

set -f

PENNY_DIR="$HOME/.penny"
mkdir -p "$PENNY_DIR" 2>/dev/null

CLAUDE_BIN=$(command -v claude 2>/dev/null || echo "/usr/local/bin/claude")

PENNY_CLI="python3 $PENNY_DIR/cli.py"

# --- First run message ---
if [ ! -f "$PENNY_DIR/first_run" ]; then
    echo ""
    echo "  Penny is now watching your Claude Code usage."
    echo "  It'll automatically use a faster mode for simple tasks."
    echo "  Run 'penny help' to learn more."
    echo ""
    touch "$PENNY_DIR/first_run" 2>/dev/null
fi

# --- Detect one-shot vs interactive ---
NON_FLAG_ARGS=()
for arg in "$@"; do
    case "$arg" in
        -*) ;;
        *) NON_FLAG_ARGS+=("$arg") ;;
    esac
done

FINAL_ARGS=("$@")

if [ "${#NON_FLAG_ARGS[@]}" -eq 1 ]; then
    # ---------- Path A: one-shot prompt ----------
    PROMPT="${NON_FLAG_ARGS[0]}"

    DECISION=$(python3 "$PENNY_DIR/heuristics.py" decide "$PROMPT" 2>>"$PENNY_DIR/error.log")
    RC=$?

    if [ $RC -ne 0 ] || [ -z "$DECISION" ]; then
        exec "$CLAUDE_BIN" "${FINAL_ARGS[@]}"
    fi

    IFS=$'\t' read -r TIER CURRENT_MODEL CURRENT_TIER CHEAPER_MODEL SAVINGS_CENTS <<< "$DECISION"

    SHOULD_SWITCH=0
    if [ -n "$CHEAPER_MODEL" ]; then
        OVER_THRESHOLD=$(python3 -c "
import json, os
p = os.path.expanduser('~/.penny/pricing.json')
up = os.path.join(os.path.dirname(p), 'pricing.json')
path = up if os.path.exists(up) else p
try:
    with open(path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}
threshold = float(cfg.get('min_savings_cents_for_switch', 5))
import sys
print(1 if float(sys.argv[1]) > threshold else 0)
" "$SAVINGS_CENTS" 2>>"$PENNY_DIR/error.log")
        if [ "$OVER_THRESHOLD" = "1" ]; then
            SHOULD_SWITCH=1
        fi
    fi

    if [ "$SHOULD_SWITCH" -eq 1 ]; then
        # Factor in user preference: conservative users get a higher bar
        PREF=$($PENNY_CLI check-preference 2>>"$PENNY_DIR/error.log")
        if [ "$PREF" = "conservative" ]; then
            OVER_THRESHOLD=$(python3 -c "
import json, os
p = os.path.expanduser('~/.penny/pricing.json')
up = os.path.join(os.path.dirname(p), 'pricing.json')
path = up if os.path.exists(up) else p
try:
    with open(path) as f:
        cfg = json.load(f)
except Exception:
    cfg = {}
threshold = float(cfg.get('min_savings_cents_for_switch', 5)) * 2
import sys
print(1 if float(sys.argv[1]) > threshold else 0)
" "$SAVINGS_CENTS" 2>>"$PENNY_DIR/error.log")
            if [ "$OVER_THRESHOLD" != "1" ]; then
                SHOULD_SWITCH=0
            fi
        fi
    fi

    if [ "$SHOULD_SWITCH" -eq 1 ]; then
        TODAY=$(date '+%Y-%m-%d')
        CAP_STATUS=$($PENNY_CLI check-cap "$TODAY" 2>>"$PENNY_DIR/error.log")

        if [ "$CAP_STATUS" = "ok" ]; then
            FINAL_ARGS+=("--model" "$CHEAPER_MODEL")
            DOLLARS=$(python3 -c "import sys; print('\${:.2f}'.format(float(sys.argv[1])/100))" "$SAVINGS_CENTS" 2>/dev/null)
            echo " Penny: using faster mode for this task (~$DOLLARS saved)" >&2
        fi
    fi

    exec "$CLAUDE_BIN" "${FINAL_ARGS[@]}"
else
    # ---------- Path B: interactive session ----------
    TODAY=$(date '+%Y-%m-%d')
    TIP=$($PENNY_CLI check-tip "$TODAY" 2>>"$PENNY_DIR/error.log")

    if [ -n "$TIP" ]; then
        echo " Penny tip: consider running 'penny set-default' to save ~$TIP/week permanently" >&2
    fi

    exec "$CLAUDE_BIN" "${FINAL_ARGS[@]}"
fi
