import os
import sys
import traceback
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rumps

import cli
import costs
import util

ERROR_LOG_PATH = os.path.join(util.PENNY_DIR, "error.log")

LIVE_SESSION_WINDOW = timedelta(minutes=2)
NOTIFY_WINDOW = timedelta(minutes=10)


def log_error(msg: str) -> None:
    try:
        os.makedirs(util.PENNY_DIR, exist_ok=True)
        with open(ERROR_LOG_PATH, "a") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except OSError:
        pass


class PennyApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("Penny", title="\U0001F4B0 $0.00")

        self.summary_item = rumps.MenuItem("$0.00 this week")
        self.summary_item.set_callback(None)
        self.save_item = rumps.MenuItem("You could save: $0.00")
        self.save_item.set_callback(None)
        self.weekly_summary_item = rumps.MenuItem("View weekly summary", callback=self.show_weekly_summary)
        self.set_default_item = rumps.MenuItem("penny set-default", callback=self.run_set_default)
        self.pause_item = rumps.MenuItem("Pause nudges", callback=self.toggle_pause)
        self.health_item = rumps.MenuItem("Penny health", callback=self.show_health)

        self.menu = [
            self.summary_item,
            self.save_item,
            None,
            self.weekly_summary_item,
            None,
            self.pause_item,
            None,
            self.health_item,
        ]

        self._sync_pause_label()
        self._sync_set_default_visibility()

        self.refresh_timer = rumps.Timer(self.refresh, 15)
        self.refresh_timer.start()

        self.notify_timer = rumps.Timer(self.check_notifications, 10)
        self.notify_timer.start()

        self.refresh(None)

    def _sync_pause_label(self) -> None:
        try:
            prefs: Dict = util.load_json(os.path.join(util.PENNY_DIR, "prefs.json"), {})
            paused = prefs.get("paused", False)
            self.pause_item.title = "Resume nudges" if paused else "Pause nudges"
        except Exception:
            log_error(traceback.format_exc())

    def _sync_set_default_visibility(self) -> None:
        try:
            prefs: Dict = util.load_json(os.path.join(util.PENNY_DIR, "prefs.json"), {})
            show = bool(prefs.get("suggested_default_switch", False))
            self.set_default_item.set_callback(self.run_set_default if show else None)
            self.set_default_item.hidden = not show
        except Exception:
            log_error(traceback.format_exc())

    def refresh(self, _: Any) -> None:
        try:
            stats = cli.weekly_stats()
            spent_str = costs.format_dollars(stats["spent_cents"])
            save_str = costs.format_dollars(stats["could_save_cents"])

            self.summary_item.title = f"{spent_str} this week"
            self.save_item.title = f"You could save: {save_str}"

            title = f"\U0001F4B0 {spent_str}"

            live: Optional[Dict] = util.load_json(os.path.join(util.PENNY_DIR, "live_session.json"), None)
            if live:
                try:
                    ts = datetime.fromisoformat(live["timestamp"])
                    if datetime.now() - ts < LIVE_SESSION_WINDOW:
                        live_cost = costs.format_dollars(live.get("cost_cents", 0))
                        title = f"{title} \u00b7 {live_cost}\u2191"
                except (KeyError, ValueError):
                    pass

            self.title = title
            self._sync_pause_label()
            self._sync_set_default_visibility()
        except Exception:
            log_error(traceback.format_exc())
            self.title = "\U0001F4B0 $0.00"

    def check_notifications(self, _: Any) -> None:
        try:
            notify_path = os.path.join(util.PENNY_DIR, "notify.json")
            if not os.path.exists(notify_path):
                return
            notif: Optional[Dict] = util.load_json(notify_path, None)
            if not notif:
                return

            try:
                ts = datetime.fromisoformat(notif["timestamp"])
            except (KeyError, ValueError):
                try:
                    os.remove(notify_path)
                except OSError:
                    pass
                return

            if datetime.now() - ts < NOTIFY_WINDOW:
                rumps.notification(title="Penny", subtitle="", message=notif.get("message", ""))

            try:
                os.remove(notify_path)
            except OSError:
                pass
        except Exception:
            log_error(traceback.format_exc())

    def show_weekly_summary(self, _: Any) -> None:
        try:
            stats = cli.weekly_stats()
            spent_str = costs.format_dollars(stats["spent_cents"])
            save_str = costs.format_dollars(stats["could_save_cents"])
            pct = round((stats["could_save_cents"] / stats["spent_cents"]) * 100) if stats["spent_cents"] > 0 else 0

            lines = [
                f"Spent:        {spent_str}",
                f"Could save:   {save_str}  ({pct}%)",
                f"Sessions:     {stats['session_count']}  ({stats['flagged_count']} flagged)",
                "",
            ]

            if stats["flagged_count"] >= 3:
                lines.append("Most of your sessions were simple tasks running")
                lines.append("on a more powerful mode than needed.")
                lines.append("")
                lines.append(f"Run this command to save ~{save_str}/week automatically:")
                lines.append("")
                lines.append("   penny set-default")
            elif stats["spent_cents"] > 2000:
                lines.append("Consider switching your default model to save more.")
            else:
                lines.append("You're already being efficient. Nice.")

            rumps.alert(title="This week with Claude Code", message="\n".join(lines))
        except Exception:
            log_error(traceback.format_exc())

    def run_set_default(self, _: Any) -> None:
        try:
            result = cli.perform_set_default()

            if not result["ok"]:
                rumps.alert(title="Penny", message=result["reason"])
                return

            save_str = costs.format_dollars(result["save_cents"])
            self._sync_set_default_visibility()

            rumps.alert(
                title="Penny",
                message=f"Default model updated to {result['tier']} mode.\nEstimated savings: ~{save_str}/week.\n\nTo undo: penny set-default --restore",
            )
        except Exception:
            log_error(traceback.format_exc())

    def toggle_pause(self, _: Any) -> None:
        try:
            prefs: Dict = util.load_json(os.path.join(util.PENNY_DIR, "prefs.json"), {})
            prefs["paused"] = not prefs.get("paused", False)
            util.write_json(os.path.join(util.PENNY_DIR, "prefs.json"), prefs)
            self._sync_pause_label()
        except Exception:
            log_error(traceback.format_exc())

    def show_health(self, _: Any) -> None:
        try:
            errors = []
            try:
                with open(ERROR_LOG_PATH) as f:
                    errors = [line for line in f if line.strip()]
            except FileNotFoundError:
                pass

            sessions = util.load_json(os.path.join(util.PENNY_DIR, "sessions.json"), [])
            count = len(sessions) if isinstance(sessions, list) else 0

            lines = [
                f"Errors: {len(errors)}",
                f"Sessions tracked: {count}",
                f"State dir: {util.PENNY_DIR}",
            ]
            rumps.alert(title="Penny Health", message="\n".join(lines))
        except Exception:
            log_error(traceback.format_exc())


if __name__ == "__main__":
    PennyApp().run()
