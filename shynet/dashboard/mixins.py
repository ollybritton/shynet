from datetime import datetime, time

from django.utils import timezone


class DateRangeMixin:
    def get_start_date(self):
        if self.request.GET.get("startDate") is not None:
            found_time = timezone.datetime.strptime(
                self.request.GET.get("startDate"), "%Y-%m-%d"
            )
            return timezone.make_aware(datetime.combine(found_time, time.min))
        else:
            return timezone.now() - timezone.timedelta(days=30)

    def get_end_date(self):
        if self.request.GET.get("endDate") is not None:
            found_time = timezone.datetime.strptime(
                self.request.GET.get("endDate"), "%Y-%m-%d"
            )
            return timezone.make_aware(datetime.combine(found_time, time.max))
        else:
            return timezone.now()

    def get_date_ranges(self):
        now = timezone.now()
        return [
            {
                "name": "Last 3 days",
                "start": now - timezone.timedelta(days=2),
                "end": now,
            },
            {
                "name": "Last 30 days",
                "start": now - timezone.timedelta(days=29),
                "end": now,
            },
            {
                "name": "Last 90 days",
                "start": now - timezone.timedelta(days=89),
                "end": now,
            },
            {
                "name": "This month",
                "start": now.replace(day=1),
                "end": now,
            },
            {
                "name": "Last month",
                "start": (now.replace(day=1) - timezone.timedelta(days=1)).replace(
                    day=1
                ),
                "end": now.replace(day=1) - timezone.timedelta(days=1),
            },
            {
                "name": "This year",
                "start": now.replace(day=1, month=1),
                "end": now,
            },
        ]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["start_date"] = self.get_start_date()
        data["end_date"] = self.get_end_date()
        data["date_ranges"] = self.get_date_ranges()

        return data


class SegmentMixin:
    """Reads the ?segment= toggle (all / humans / bots) and exposes it.

    Defaults to "humans" so the dashboard shows real-user traffic out of the
    box. The model layer defaults to "all", so this default only applies to
    the views that mix this in (not the API or digests)."""

    SEGMENTS = ["humans", "bots", "all"]
    DEFAULT_SEGMENT = "humans"

    def get_segment(self):
        segment = self.request.GET.get("segment")
        if segment not in self.SEGMENTS:
            return self.DEFAULT_SEGMENT
        return segment

    def get_segment_options(self):
        labels = {"humans": "Humans", "bots": "Bots", "all": "All"}
        active = self.get_segment()
        return [
            {"value": value, "name": labels[value], "active": value == active}
            for value in self.SEGMENTS
        ]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["segment"] = self.get_segment()
        data["segment_options"] = self.get_segment_options()
        return data


class EngagedMixin:
    """Reads the ?engaged= toggle and exposes it.

    "Engaged only" hides zero-duration bounce sessions (and most "Unknown"
    noise) from every KPI, chart and breakdown. Defaults to OFF so existing
    behaviour, the API and digests are unaffected; only views that mix this in
    and explicitly pass ?engaged=true opt in. Composes orthogonally with the
    bot/human SegmentMixin."""

    def get_engaged(self):
        return self.request.GET.get("engaged") == "true"

    def get_engaged_options(self):
        active = self.get_engaged()
        return [
            {"value": "true", "name": "Engaged", "active": active},
            {"value": "", "name": "All sessions", "active": not active},
        ]

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["engaged"] = self.get_engaged()
        data["engaged_options"] = self.get_engaged_options()
        return data
