import json
import logging
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone

logger = logging.getLogger(__name__)

NOTEBOOK_NAME = 'JSON Sandbox'
MAX_NOTE_PAYLOAD_BYTES = 1024 * 1024


def _check_staff(user):
    if not user.is_staff:
        raise PermissionDenied


def _fenced(text, lang=''):
    """Markdown fenced block; the fence is longer than any backtick run inside the text."""
    longest = max((len(run) for run in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}{lang}\n{text}\n{fence}'


def build_note_body(mode, payload, expression, filter_expr, result, filter_matched, evaluated=False):
    """Plain sections with fenced blocks; empty sections are skipped. The content is stored as typed,
    never re-evaluated. `result` is the JSONPath output (None when it did not evaluate or had no
    matches); `filter_matched` is None when the filter was not evaluated; `evaluated` says the JSONPath
    expression ran without an error, so an empty `result` means "no matches"."""
    sections = [f'Mode: {mode}']
    if payload.strip():
        sections.append('Payload:\n' + _fenced(payload.strip(), 'json'))
    if mode == 'jsonpath':
        if expression.strip():
            sections.append('JSONPath:\n' + _fenced(expression.strip()))
            if result is not None:
                sections.append('Result:\n' + _fenced(result, 'json'))
            elif evaluated:
                sections.append('Result: no matches')
    else:
        if filter_expr.strip():
            sections.append('Filter:\n' + _fenced(filter_expr.strip(), 'json'))
            if filter_matched is not None:
                sections.append('Filter matched: ' + ('yes' if filter_matched else 'no'))
    return '\n\n'.join(sections) + '\n'


def _save_as_note(request, mode, payload, expression, filter_expr, result, filter_matched, evaluated):
    """Creates the note in the user's JSON Sandbox notebook. Returns a redirect, or None after
    adding an error message when nothing was saved."""
    from notes.models import Note, Notebook

    if not (payload.strip() or expression.strip() or filter_expr.strip()):
        messages.error(request, 'Nothing to save: the payload, expression and filter are empty.')
        return None
    if len(payload.encode('utf-8')) > MAX_NOTE_PAYLOAD_BYTES:
        messages.error(request, 'The payload is too large to save as a note (limit 1 MB).')
        return None
    title = request.POST.get('note_title', '').strip()[:255]
    if not title:
        title = 'JSON sandbox - ' + timezone.localtime().strftime('%Y-%m-%d %H:%M')
    notebook, _ = Notebook.objects.get_or_create(owner=request.user, name=NOTEBOOK_NAME)
    note = Note.objects.create(
        title=title, owner=request.user, notebook=notebook,
        body=build_note_body(mode, payload, expression, filter_expr, result, filter_matched, evaluated),
    )
    messages.success(request, f'Saved to note "{title}".')
    return redirect('note-edit', pk=note.pk)


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

    if request.method == 'POST' and request.POST.get('save_note'):
        saved = _save_as_note(
            request, mode, payload_input, expression_input, filter_input, result, filter_matched,
            evaluated=error is None,
        )
        if saved:
            return saved

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
