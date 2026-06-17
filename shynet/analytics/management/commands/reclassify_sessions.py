"""Re-run bot classification over existing sessions.

Upstream only flagged self-identifying robots at ingest, so historical data
predating the improved detection (and the is_bot flag) leaves crawlers mixed
in with real users. This command re-derives device_type / is_bot / bot_reason
from each session's stored user agent so the dashboard segmentation works on
data collected before the fork.

Dry-run by default; pass --commit to persist.
"""

import user_agents
from django.core.management.base import BaseCommand

from analytics import bot_detection
from analytics.models import Session


class Command(BaseCommand):
    help = "Re-run bot classification over existing sessions using stored user agents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Persist changes. Without this flag the command only reports.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=2000,
            help="Number of rows to update per bulk_update call.",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        batch_size = options["batch_size"]

        qs = Session.objects.all().only(
            "uuid", "user_agent", "device_type", "is_bot", "bot_reason"
        )
        total = qs.count()

        processed = 0
        changed = 0
        reason_counts = {}
        pending = []

        # Pixel reclassification needs per-session hit history; keep this pass
        # user-agent-only so it is fast and deterministic.
        for session in qs.iterator(chunk_size=batch_size):
            ua = user_agents.parse(session.user_agent or "")
            device_type, is_bot, bot_reason = bot_detection.classify(
                session.user_agent or "", ua, tracker=None, treat_pixel_as_bot=False
            )
            processed += 1
            if (
                is_bot != session.is_bot
                or bot_reason != session.bot_reason
                or device_type != session.device_type
            ):
                session.is_bot = is_bot
                session.bot_reason = bot_reason
                session.device_type = device_type
                changed += 1
                if is_bot:
                    reason_counts[bot_reason] = reason_counts.get(bot_reason, 0) + 1
                if commit:
                    pending.append(session)
                    if len(pending) >= batch_size:
                        Session.objects.bulk_update(
                            pending, ["is_bot", "bot_reason", "device_type"]
                        )
                        pending = []

        if commit and pending:
            Session.objects.bulk_update(
                pending, ["is_bot", "bot_reason", "device_type"]
            )

        self.stdout.write(
            f"processed={total} changed={changed} commit={commit}"
        )
        for reason, count in sorted(
            reason_counts.items(), key=lambda kv: kv[1], reverse=True
        ):
            self.stdout.write(f"  newly flagged bot [{reason}]: {count}")
        if not commit:
            self.stdout.write(
                self.style.WARNING("Dry run; re-run with --commit to apply.")
            )
