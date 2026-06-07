import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def dispatch(source, payload):
    """
    Entry point called by integration apps after receiving an event.
    Evaluates all active Triggers for the given source and executes matching Actions.
    Never raises — errors are logged and written to TriggerLog.
    """
    try:
        _dispatch(source, payload)
    except Exception as exc:
        logger.error('automations_dispatch_fatal', extra={'source': source, 'error': str(exc)})


def _dispatch(source, payload):
    from .models import Trigger, TriggerLog
    from .evaluator import evaluate_filter

    triggers = Trigger.objects.filter(source=source, is_active=True).select_related('action')

    for trigger in triggers:
        if not trigger.action.is_active:
            continue

        matched = evaluate_filter(trigger.filter, payload)

        if not matched:
            TriggerLog.objects.create(
                trigger=trigger,
                action=trigger.action,
                payload_snapshot=payload,
                result=TriggerLog.RESULT_SKIPPED,
            )
            logger.debug('automations_trigger_skipped', extra={'trigger_id': trigger.pk})
            continue

        try:
            with transaction.atomic():
                _execute_action(trigger.action, payload)
            TriggerLog.objects.create(
                trigger=trigger,
                action=trigger.action,
                payload_snapshot=payload,
                result=TriggerLog.RESULT_MATCHED,
            )
            logger.info(
                'automations_trigger_matched',
                extra={'trigger_id': trigger.pk, 'action_id': trigger.action.pk},
            )
        except Exception as exc:
            TriggerLog.objects.create(
                trigger=trigger,
                action=trigger.action,
                payload_snapshot=payload,
                result=TriggerLog.RESULT_ERROR,
                detail=str(exc),
            )
            logger.error(
                'automations_trigger_error',
                extra={'trigger_id': trigger.pk, 'error': str(exc)},
            )


def _execute_action(action, payload):
    if action.action_type == 'create_ticket':
        _upsert_ticket(action, payload)
    else:
        raise ValueError(f"Unknown action_type: {action.action_type}")


_TRACKED_FIELDS = ['title', 'description', 'type', 'priority', 'category', 'service', 'sub_service', 'creator_name']


def _resolve_fields(mappings, payload):
    from .resolver import resolve_value
    from itsm.models import Category, Ticket

    resolved = {field: resolve_value(expr, payload) for field, expr in mappings.items()}

    title = resolved.get('title') or ''
    description = resolved.get('description') or ''
    ticket_type = resolved.get('type') or Ticket.TYPE_INCIDENT
    priority = resolved.get('priority') or Ticket.PRIORITY_MEDIUM

    if ticket_type not in dict(Ticket.TYPES):
        ticket_type = Ticket.TYPE_INCIDENT
    if priority not in dict(Ticket.PRIORITIES):
        priority = Ticket.PRIORITY_MEDIUM

    category = None
    category_name = resolved.get('category')
    if category_name:
        category, _ = Category.objects.get_or_create(name=category_name)

    return {
        'title': title,
        'description': description,
        'type': ticket_type,
        'priority': priority,
        'category': category,
        'creator_name': resolved.get('creator') or '',
        'service': resolved.get('service') or '',
        'sub_service': resolved.get('sub_service') or '',
        'key': resolved.get('key') or '',
    }


def _upsert_ticket(action, payload):
    from itsm.models import Ticket
    from .resolver import resolve_value

    fields = _resolve_fields(action.field_mappings, payload)

    # external_id: prefer field_mappings["key"], fall back to dedup_expression
    external_id = fields['key']
    if not external_id and action.dedup_expression:
        raw = resolve_value(action.dedup_expression, payload)
        if raw:
            external_id = str(raw)

    if external_id:
        existing = Ticket.objects.filter(external_id=external_id).first()
        if existing:
            _update_ticket(existing, fields, action.system_user)
            logger.info('automations_ticket_updated', extra={'ticket_id': existing.pk, 'external_id': external_id})
            return

    Ticket.objects.create(
        title=fields['title'],
        description=fields['description'],
        type=fields['type'],
        priority=fields['priority'],
        requester=action.system_user,
        category=fields['category'],
        creator_name=fields['creator_name'],
        service=fields['service'],
        sub_service=fields['sub_service'],
        external_id=external_id,
    )


def _ticket_field_str(ticket, field):
    value = getattr(ticket, field, None)
    return str(value) if value is not None else ''


def _update_ticket(ticket, fields, system_user):
    from itsm.models import TicketEvent

    old = {f: _ticket_field_str(ticket, f) for f in _TRACKED_FIELDS}

    ticket.title = fields['title']
    ticket.description = fields['description']
    ticket.type = fields['type']
    ticket.priority = fields['priority']
    ticket.category = fields['category']
    ticket.creator_name = fields['creator_name']
    ticket.service = fields['service']
    ticket.sub_service = fields['sub_service']
    ticket.save()

    ticket.refresh_from_db()
    new = {f: _ticket_field_str(ticket, f) for f in _TRACKED_FIELDS}

    for field in _TRACKED_FIELDS:
        if old[field] != new[field]:
            TicketEvent.objects.create(
                ticket=ticket,
                actor=system_user,
                field_name=field,
                old_value=old[field],
                new_value=new[field],
            )
