import logging

from .resolver import resolve_value

logger = logging.getLogger(__name__)


def evaluate_filter(condition, payload):
    """
    Evaluate a structured filter condition tree against a payload dict.
    Returns True if the payload matches, False otherwise.
    A missing JSONPath always returns False — never raises.

    Supported condition shapes:
      {"and": [...]}
      {"or": [...]}
      {"path": "$.x", "op": "eq|neq|in|not_in|contains", "value": <any>}
    """
    if not condition:
        return True

    if 'and' in condition:
        return all(evaluate_filter(c, payload) for c in condition['and'])

    if 'or' in condition:
        return any(evaluate_filter(c, payload) for c in condition['or'])

    path = condition.get('path')
    op = condition.get('op')
    expected = condition.get('value')

    if not path or not op:
        logger.debug('automations_evaluator_invalid_condition', extra={'condition': condition})
        return False

    actual = resolve_value(path, payload)
    if actual is None:
        return False

    try:
        if op == 'eq':
            return actual == expected
        if op == 'neq':
            return actual != expected
        if op == 'in':
            if isinstance(actual, list):
                return any(item in expected for item in actual)
            return actual in expected
        if op == 'not_in':
            if isinstance(actual, list):
                return not any(item in expected for item in actual)
            return actual not in expected
        if op == 'contains':
            return expected in actual
    except Exception:
        logger.debug('automations_evaluator_comparison_error', extra={'path': path, 'op': op})
        return False

    logger.debug('automations_evaluator_unknown_op', extra={'op': op})
    return False
