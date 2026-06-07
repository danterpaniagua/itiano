import logging
import re

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
      {"path": "$.x", "op": "<operator>", "value": <any>}

    Operators:
      eq          exact equality
      neq         exact inequality
      eq_ci       case-insensitive equality
      in          value (or any item if list) is in expected list
      not_in      value (or no item if list) is in expected list
      in_ci       case-insensitive version of in
      not_in_ci   case-insensitive version of not_in
      contains    expected is a substring of actual
      exists      path resolves to a non-empty value (no value field needed)
      regex       actual (or any item if list) matches regex pattern in value
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

    if op == 'exists':
        actual = resolve_value(path, payload)
        return actual is not None and actual != [] and actual != ''

    actual = resolve_value(path, payload)
    if actual is None:
        return False

    try:
        if op == 'eq':
            return actual == expected
        if op == 'neq':
            return actual != expected
        if op == 'eq_ci':
            return str(actual).lower() == str(expected).lower()
        if op == 'in':
            if isinstance(actual, list):
                return any(item in expected for item in actual)
            return actual in expected
        if op == 'not_in':
            if isinstance(actual, list):
                return not any(item in expected for item in actual)
            return actual not in expected
        if op == 'in_ci':
            expected_lower = [str(e).lower() for e in expected]
            if isinstance(actual, list):
                return any(str(item).lower() in expected_lower for item in actual)
            return str(actual).lower() in expected_lower
        if op == 'not_in_ci':
            expected_lower = [str(e).lower() for e in expected]
            if isinstance(actual, list):
                return not any(str(item).lower() in expected_lower for item in actual)
            return str(actual).lower() not in expected_lower
        if op == 'contains':
            return expected in actual
        if op == 'regex':
            pattern = re.compile(expected)
            if isinstance(actual, list):
                return any(pattern.search(str(item)) for item in actual)
            return bool(pattern.search(str(actual)))
    except Exception:
        logger.debug('automations_evaluator_comparison_error', extra={'path': path, 'op': op})
        return False

    logger.debug('automations_evaluator_unknown_op', extra={'op': op})
    return False
