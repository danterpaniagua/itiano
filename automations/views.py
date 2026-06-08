import logging
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ActionForm, TriggerForm
from .models import Action, ActionHistory, Trigger, TriggerHistory, TriggerLog

_ACTION_TRACKED = ['name', 'action_type', 'description_format', 'field_mappings', 'tag_expressions', 'system_user', 'dedup_expression', 'is_active']
_TRIGGER_TRACKED = ['name', 'source', 'filter', 'action', 'is_active']


def _snapshot(instance, fields):
    snap = {}
    for f in fields:
        val = getattr(instance, f, None)
        snap[f] = str(val.pk) if hasattr(val, 'pk') else ('' if val is None else str(val))
    return snap


def _record_history(history_model, fk_name, instance, user, before, after):
    records = [
        history_model(**{fk_name: instance, 'user': user, 'field_name': f, 'old_value': before[f], 'new_value': after[f]})
        for f in before if before[f] != after.get(f, '')
    ]
    if records:
        history_model.objects.bulk_create(records)

logger = logging.getLogger(__name__)


def staff_required(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return wrapped


@staff_required
def index(request):
    return redirect('automations-action-list')


# ── Actions ────────────────────────────────────────────────────────────────────

@staff_required
def action_list(request):
    actions = Action.objects.prefetch_related('triggers')
    return render(request, 'automations/action_list.html', {
        'actions': actions,
        'section': 'actions',
    })


@staff_required
def action_create(request):
    form = ActionForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, 'Action created.')
        return redirect('automations-action-list')
    return render(request, 'automations/action_form.html', {
        'form': form,
        'title': 'New Action',
        'section': 'actions',
        'cancel_url': 'automations-action-list',
    })


@staff_required
def action_edit(request, pk):
    action = get_object_or_404(Action, pk=pk)
    form = ActionForm(request.POST or None, instance=action)
    if form.is_valid():
        if not form.has_changed():
            messages.info(request, 'No changes detected.')
            return redirect('automations-action-list')
        before = _snapshot(action, _ACTION_TRACKED)
        form.save()
        action.refresh_from_db()
        _record_history(ActionHistory, 'action', action, request.user, before, _snapshot(action, _ACTION_TRACKED))
        messages.success(request, 'Action updated.')
        return redirect('automations-action-list')
    history = action.history.select_related('user')[:20]
    return render(request, 'automations/action_form.html', {
        'form': form,
        'title': 'Edit Action',
        'section': 'actions',
        'cancel_url': 'automations-action-list',
        'history': history,
    })


@staff_required
@require_POST
def action_toggle(request, pk):
    action = get_object_or_404(Action, pk=pk)
    action.is_active = not action.is_active
    action.save()
    return redirect('automations-action-list')


# ── Triggers ───────────────────────────────────────────────────────────────────

@staff_required
def trigger_list(request):
    triggers = Trigger.objects.select_related('action')
    return render(request, 'automations/trigger_list.html', {
        'triggers': triggers,
        'section': 'triggers',
    })


@staff_required
def trigger_create(request):
    form = TriggerForm(request.POST or None)
    if form.is_valid():
        form.save()
        messages.success(request, 'Trigger created.')
        return redirect('automations-trigger-list')
    return render(request, 'automations/trigger_form.html', {
        'form': form,
        'title': 'New Trigger',
        'section': 'triggers',
        'cancel_url': 'automations-trigger-list',
    })


@staff_required
def trigger_edit(request, pk):
    trigger = get_object_or_404(Trigger, pk=pk)
    form = TriggerForm(request.POST or None, instance=trigger)
    if form.is_valid():
        if not form.has_changed():
            messages.info(request, 'No changes detected.')
            return redirect('automations-trigger-list')
        before = _snapshot(trigger, _TRIGGER_TRACKED)
        form.save()
        trigger.refresh_from_db()
        _record_history(TriggerHistory, 'trigger', trigger, request.user, before, _snapshot(trigger, _TRIGGER_TRACKED))
        messages.success(request, 'Trigger updated.')
        return redirect('automations-trigger-list')
    history = trigger.history.select_related('user')[:20]
    return render(request, 'automations/trigger_form.html', {
        'form': form,
        'title': 'Edit Trigger',
        'section': 'triggers',
        'cancel_url': 'automations-trigger-list',
        'history': history,
    })


@staff_required
@require_POST
def trigger_toggle(request, pk):
    trigger = get_object_or_404(Trigger, pk=pk)
    trigger.is_active = not trigger.is_active
    trigger.save()
    return redirect('automations-trigger-list')


# ── Logs ───────────────────────────────────────────────────────────────────────

@staff_required
def log_list(request):
    from django.db.models import OuterRef, Subquery

    result_filter = request.GET.get('result', '')
    source_filter = request.GET.get('source', '')

    latest = TriggerLog.objects.filter(trigger=OuterRef('pk')).order_by('-created_at')

    triggers = Trigger.objects.select_related('action').annotate(
        last_result=Subquery(latest.values('result')[:1]),
        last_log_at=Subquery(latest.values('created_at')[:1]),
        last_detail=Subquery(latest.values('detail')[:1]),
        last_log_id=Subquery(latest.values('pk')[:1]),
    )

    if result_filter:
        triggers = triggers.filter(last_result=result_filter)
    if source_filter:
        triggers = triggers.filter(source=source_filter)

    return render(request, 'automations/log_list.html', {
        'triggers': triggers,
        'result_filter': result_filter,
        'source_filter': source_filter,
        'result_choices': TriggerLog.RESULTS,
        'source_choices': Trigger.SOURCES,
        'section': 'logs',
    })


@staff_required
def log_detail(request, pk):
    log = get_object_or_404(TriggerLog.objects.select_related('trigger', 'trigger__action', 'action'), pk=pk)
    return render(request, 'automations/log_detail.html', {
        'log': log,
        'section': 'logs',
    })
