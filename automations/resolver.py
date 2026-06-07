import logging

from jsonpath_ng import parse

logger = logging.getLogger(__name__)


def resolve_value(expression, payload):
    """
    Return the value at a JSONPath expression within payload, or the expression itself
    if it is not a JSONPath (i.e. a literal). Returns None when the path yields no match.
    """
    if not isinstance(expression, str) or not expression.startswith('$'):
        return expression

    try:
        matches = parse(expression).find(payload)
    except Exception:
        logger.debug('automations_resolver_parse_error', extra={'expression': expression})
        return None

    if not matches:
        logger.debug('automations_resolver_no_match', extra={'expression': expression})
        return None

    return matches[0].value
