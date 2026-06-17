from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.cache import cache
from django.db.models import Q, Count, Min, Max, F
from django.shortcuts import get_object_or_404, render, reverse, redirect
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
    View,
)
from rules.contrib.views import PermissionRequiredMixin

from analytics.models import Session, Hit
from core.models import Service, _default_api_token, RESULTS_LIMIT

from .forms import ServiceForm
from .mixins import DateRangeMixin, SegmentMixin, EngagedMixin


class DashboardView(
    LoginRequiredMixin, DateRangeMixin, SegmentMixin, EngagedMixin, ListView
):
    model = Service
    template_name = "dashboard/pages/dashboard.html"
    paginate_by = settings.DASHBOARD_PAGE_SIZE

    def get_queryset(self):
        return Service.objects.filter(
            Q(owner=self.request.user) | Q(collaborators__in=[self.request.user])
        ).distinct()

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)

        for service in data["object_list"]:
            service.stats = service.get_core_stats(
                self.get_start_date(),
                self.get_end_date(),
                self.get_segment(),
                self.get_engaged(),
            )

        return data


class ServiceCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Service
    form_class = ServiceForm
    template_name = "dashboard/pages/service_create.html"
    permission_required = "core.create_service"

    def form_valid(self, form):
        form.instance.owner = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("dashboard:service", kwargs={"pk": self.object.uuid})


class ServiceView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DateRangeMixin,
    SegmentMixin,
    EngagedMixin,
    DetailView,
):
    model = Service
    template_name = "dashboard/pages/service.html"
    permission_required = "core.view_service"

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["script_protocol"] = "https://" if settings.SCRIPT_USE_HTTPS else "http://"
        data["stats"] = self.object.get_core_stats(
            data["start_date"], data["end_date"], self.get_segment(), self.get_engaged()
        )
        data["RESULTS_LIMIT"] = RESULTS_LIMIT
        recent_sessions = (
            Session.objects.filter(
                service=self.get_object(),
                start_time__lt=self.get_end_date(),
                start_time__gt=self.get_start_date(),
            )
            .annotate(num_hits=Count("hit"))
            .order_by("-start_time")
        )
        if self.get_segment() == "humans":
            recent_sessions = recent_sessions.filter(is_bot=False)
        elif self.get_segment() == "bots":
            recent_sessions = recent_sessions.filter(is_bot=True)
        if self.get_engaged():
            recent_sessions = recent_sessions.filter(
                Q(is_bounce=False) | Q(last_seen__gt=F("start_time"))
            )
        data["object_list"] = recent_sessions[:10]
        return data


class ServiceUpdateView(
    LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, UpdateView
):
    model = Service
    form_class = ServiceForm
    template_name = "dashboard/pages/service_update.html"
    permission_required = "core.change_service"
    success_message = "Your changes were saved successfully."

    def get_success_url(self):
        return reverse("dashboard:service", kwargs={"pk": self.object.uuid})

    def form_valid(self, *args, **kwargs):
        resp = super().form_valid(*args, **kwargs)
        cache.set(
            f"service_origins_{self.object.uuid}", self.object.origins, timeout=3600
        )
        cache.set(
            f"script_inject_{self.object.uuid}", self.object.script_inject, timeout=3600
        )
        return resp

    def get_context_data(self, *args, **kwargs):
        data = super().get_context_data(*args, **kwargs)
        data["script_protocol"] = "https://" if settings.SCRIPT_USE_HTTPS else "http://"
        return data


class ServiceDeleteView(
    LoginRequiredMixin, PermissionRequiredMixin, SuccessMessageMixin, DeleteView
):
    model = Service
    form_class = ServiceForm
    template_name = "dashboard/pages/service_delete.html"
    permission_required = "core.delete_service"
    success_message = "The service was deleted successfully."

    def get_success_url(self):
        return reverse("dashboard:dashboard")


class ServiceSessionsListView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DateRangeMixin,
    SegmentMixin,
    EngagedMixin,
    ListView,
):
    model = Session
    template_name = "dashboard/pages/service_session_list.html"
    paginate_by = 20
    permission_required = "core.view_service"

    def get_object(self):
        return get_object_or_404(Service, pk=self.kwargs.get("pk"))

    def get_identifier(self):
        """Optional ?identifier= deep-link filter (from Repeat visitors)."""
        identifier = self.request.GET.get("identifier")
        if identifier:
            return identifier
        return None

    def get_queryset(self):
        sessions = (
            Session.objects.filter(
                service=self.get_object(),
                start_time__lt=self.get_end_date(),
                start_time__gt=self.get_start_date(),
            )
            .annotate(num_hits=Count("hit"))
            .order_by("-start_time")
        )
        if self.get_segment() == "humans":
            sessions = sessions.filter(is_bot=False)
        elif self.get_segment() == "bots":
            sessions = sessions.filter(is_bot=True)
        if self.get_engaged():
            sessions = sessions.filter(
                Q(is_bounce=False) | Q(last_seen__gt=F("start_time"))
            )
        if self.get_identifier() is not None:
            sessions = sessions.filter(identifier=self.get_identifier())
        return sessions

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["object"] = self.get_object()
        data["identifier"] = self.get_identifier()
        return data

    def get(self, request, *args, **kwargs):
        """Serve just the session rows for infinite scroll when ?partial=1.

        Progressive enhancement: the full page still renders normally (with a
        noscript pagination fallback), but the client-side infinite scroll
        fetches subsequent pages as lightweight row fragments. The next page
        number is returned in the X-Next-Page header so the client knows when
        to stop.
        """
        if not request.GET.get("partial"):
            return super().get(request, *args, **kwargs)

        self.object_list = self.get_queryset()
        context = self.get_context_data()
        response = render(
            request, "dashboard/includes/_session_rows.html", context
        )
        page_obj = context.get("page_obj")
        if page_obj is not None and page_obj.has_next():
            response["X-Next-Page"] = str(page_obj.next_page_number())
        return response


class ServiceLocationsListView(
    LoginRequiredMixin, PermissionRequiredMixin, DateRangeMixin, ListView
):
    model = Hit
    template_name = "dashboard/pages/service_location_list.html"
    paginate_by = RESULTS_LIMIT
    permission_required = "core.view_service"

    def get_object(self):
        return get_object_or_404(Service, pk=self.kwargs.get("pk"))

    def get_queryset(self):
        hits = Hit.objects.filter(
            service=self.get_object(),
            start_time__lt=self.get_end_date(),
            start_time__gt=self.get_start_date(),
        )
        self.hit_count = hits.count()

        return (
            hits.values("location").annotate(count=Count("location")).order_by("-count")
        )

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["object"] = self.get_object()
        data["hit_count"] = self.hit_count
        return data


class ServiceSessionView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Session
    template_name = "dashboard/pages/service_session.html"
    pk_url_kwarg = "session_pk"
    context_object_name = "session"
    permission_required = "core.view_service"

    def get_permission_object(self, **kwargs):
        return self.get_object().service

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["object"] = get_object_or_404(Service, pk=self.kwargs.get("pk"))

        session = self.object
        # Hit.Meta orders by -start_time; reverse for a chronological journey.
        hits = list(session.hit_set.all().order_by("start_time"))
        total = len(hits)
        # Pre-compute the per-hit timeline data the drill-down template needs:
        # 1-based step number, total step count and cumulative offset from the
        # session start (a timedelta the naturaldelta filter can format).
        timeline = []
        for index, hit in enumerate(hits):
            timeline.append(
                {
                    "hit": hit,
                    "step": index + 1,
                    "total": total,
                    "cumulative": hit.start_time - session.start_time,
                }
            )
        data["timeline"] = timeline
        data["hit_total"] = total
        return data


class ServiceRepeatVisitorsView(
    LoginRequiredMixin,
    PermissionRequiredMixin,
    DateRangeMixin,
    SegmentMixin,
    EngagedMixin,
    ListView,
):
    """Repeat visitors, honest about AGGRESSIVE_HASH_SALTING.

    Primary (Section A): identifier-based grouping. This is the only truthful
    cross-day answer, because session hashes are re-salted daily, so without an
    explicit window.shynet.identifier cross-day identity is impossible.

    Secondary (Section B): a same-day IP+UA fallback cluster, fenced behind a
    warning. Rendered read-only aggregation, never as an identity. ip and
    user_agent are PII and may be null when IP collection is disabled."""

    model = Session
    template_name = "dashboard/pages/service_repeat_visitors.html"
    paginate_by = 50
    permission_required = "core.view_service"

    def get_object(self):
        return get_object_or_404(Service, pk=self.kwargs.get("pk"))

    def _base_sessions(self):
        sessions = Session.objects.filter(
            service=self.get_object(),
            start_time__lt=self.get_end_date(),
            start_time__gt=self.get_start_date(),
        )
        if self.get_segment() == "humans":
            sessions = sessions.filter(is_bot=False)
        elif self.get_segment() == "bots":
            sessions = sessions.filter(is_bot=True)
        if self.get_engaged():
            sessions = sessions.filter(
                Q(is_bounce=False) | Q(last_seen__gt=F("start_time"))
            )
        return sessions

    def get_queryset(self):
        # Section A: cross-day, identifier-based. The honest primary view.
        return (
            self._base_sessions()
            .exclude(identifier="")
            .filter(identifier__isnull=False)
            .values("identifier")
            .annotate(
                count=Count("uuid"),
                first_seen=Min("start_time"),
                last_seen=Max("last_seen"),
            )
            .filter(count__gt=1)
            .order_by("-count", "-last_seen")
        )

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["object"] = self.get_object()

        # Section B: same-day best-effort IP+UA clusters. Read-only aggregation,
        # never rendered as an identity. Excludes rows with no IP (IP collection
        # disabled) since those cannot be meaningfully clustered.
        ip_ua_clusters = (
            self._base_sessions()
            .filter(ip__isnull=False)
            .values("ip", "user_agent")
            .annotate(
                count=Count("uuid"),
                first_seen=Min("start_time"),
                last_seen=Max("last_seen"),
            )
            .filter(count__gt=1)
            .order_by("-count", "-last_seen")[:RESULTS_LIMIT]
        )
        data["ip_ua_clusters"] = ip_ua_clusters
        return data


class RefreshApiTokenView(LoginRequiredMixin, View):
    def post(self, request):
        request.user.api_token = _default_api_token()
        request.user.save()
        return redirect("account_change_password")
