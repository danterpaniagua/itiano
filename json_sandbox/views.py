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
    result = None
    error = None

    show_back = bool(request.GET.get('back') or request.POST.get('back'))

    if request.method == 'POST':
        payload_input = request.POST.get('payload', '')
        expression_input = request.POST.get('expression', '')

        try:
            data = json.loads(payload_input)
        except json.JSONDecodeError as e:
            error = f"Invalid JSON: {e}"
        else:
            if expression_input.strip():
                try:
                    from jsonpath_ng import parse
                    matches = [m.value for m in parse(expression_input).find(data)]
                    result = json.dumps(matches, indent=2)
                except Exception as e:
                    error = f"JSONPath error: {e}"

    return render(request, 'json_sandbox/sandbox.html', {
        'payload_input': payload_input,
        'expression_input': expression_input,
        'result': result,
        'error': error,
        'show_back': show_back,
    })
