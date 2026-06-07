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
        _create_ticket(action, payload)
    else:
        raise ValueError(f"Unknown action_type: {action.action_type}")


def _create_ticket(action, payload):
    from itsm.models import Category, Ticket
    from .resolver import resolve_value

    mappings = action.field_mappings
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

    Ticket.objects.create(
        title=title,
        description=description,
        type=ticket_type,
        priority=priority,
        requester=action.system_user,
        category=category,
        creator_name=resolved.get('creator') or '',
        service=resolved.get('service') or '',
        sub_service=resolved.get('sub_service') or '',
    )
