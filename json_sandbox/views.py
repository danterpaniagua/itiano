import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

logger = logging.getLogger(__name__)


def _check_staff(user):
    if not user.is_staff:
        raise PermissionDenied


@login_required
def sandbox(request):
    _check_staff(request.user)

    payload_input = request.session.pop('sandbox_payload', '')
    expression_input = ''
    filter_input = ''
    result = None
    filter_matched = None
    error = None
    mode = 'jsonpath'

    show_back = bool(request.GET.get('back') or request.POST.get('back'))

    if request.method == 'POST':
        mode = request.POST.get('mode', 'jsonpath')
        payload_input = request.POST.get('payload', '')
        expression_input = request.POST.get('expression', '')
        filter_input = request.POST.get('filter_expr', '')

        try:
            data = json.loads(payload_input)
        except json.JSONDecodeError as e:
            error = f"Invalid JSON payload: {e}"
        else:
            if mode == 'jsonpath' and expression_input.strip():
                try:
                    from jsonpath_ng import parse
                    matches = [m.value for m in parse(expression_input).find(data)]
                    result = json.dumps(matches, indent=2) if matches else None
                except Exception as e:
                    error = f"JSONPath error: {e}"

            elif mode == 'filter' and filter_input.strip():
                try:
                    condition = json.loads(filter_input)
                except json.JSONDecodeError as e:
                    error = f"Invalid filter JSON: {e}"
                else:
                    try:
                        from automations.evaluator import evaluate_filter
                        filter_matched = evaluate_filter(condition, data)
                    except Exception as e:
                        error = f"Filter error: {e}"

    return render(request, 'json_sandbox/sandbox.html', {
        'payload_input': payload_input,
        'expression_input': expression_input,
        'filter_input': filter_input,
        'result': result,
        'filter_matched': filter_matched,
        'error': error,
        'show_back': show_back,
        'mode': mode,
    })
