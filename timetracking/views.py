import datetime
import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from jira_integration.models import JiraEvent, JiraTicket
from settings_hub.models import get_app_setting, JiraStatusConfig

from .models import TimeEntry, WorkSchedule


class TimeEntryListView(LoginRequiredMixin, View):
    def get(self, request):
        entries = TimeEntry.objects.filter(user=request.user).select_related('jira_ticket')
        ticket_filter = request.GET.get('ticket', '').strip()
        if ticket_filter:
            entries = entries.filter(jira_ticket__issue_key__icontains=ticket_filter)

        schedule = WorkSchedule.objects.filter(user=request.user).first()
        jira_username = schedule.jira_username.strip() if schedule and schedule.jira_username else ''
        try:
            jira_account_id = request.user.userprofile.jira_account_id.strip()
        except Exception:
            jira_account_id = ''
        active_tickets = []
        if jira_account_id or jira_username:
            _ip_names = list(JiraStatusConfig.objects.filter(
                category='in_progress').values_list('status_name', flat=True)) or ['In Progress']
            qs = JiraTicket.objects.filter(status__in=_ip_names, is_deleted=False)
            if jira_account_id:
                qs = qs.filter(assignee_account_id=jira_account_id)
            else:
                qs = qs.filter(assignee__iexact=jira_username)
            active_tickets = list(qs.order_by('issue_key'))

        return render(request, 'timetracking/entry_list.html', {
            'entries': entries,
            'ticket_filter': ticket_filter,
            'active_tickets': active_tickets,
            'jira_username': jira_username,
        })


class TimeEntryCreateView(LoginRequiredMixin, View):
    def _get_ticket(self, issue_key):
        if issue_key:
            return JiraTicket.objects.filter(issue_key=issue_key).first()
        return None

    def get(self, request):
        ticket = self._get_ticket(request.GET.get('ticket', ''))
        tickets = JiraTicket.objects.order_by('issue_key')
        return render(request, 'timetracking/entry_form.html', {
            'tickets': tickets,
            'preselected_ticket': ticket,
            'today': datetime.date.today().isoformat(),
            'entry': None,
        })

    def post(self, request):
        issue_key = request.POST.get('jira_ticket', '').strip()
        date_str = request.POST.get('date', '').strip()
        minutes_str = request.POST.get('minutes', '').strip()
        activity = request.POST.get('activity', '').strip()

        errors = []
        ticket = JiraTicket.objects.filter(issue_key=issue_key).first()
        if not ticket:
            errors.append('Selecciona un ticket Jira válido.')
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError:
            errors.append('Fecha inválida.')
            date = None
        try:
            minutes = int(minutes_str)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            errors.append('Los minutos deben ser un número positivo.')
            minutes = None
        if not activity:
            errors.append('La actividad es obligatoria.')

        if errors:
            for e in errors:
                messages.error(request, e)
            tickets = JiraTicket.objects.order_by('issue_key')
            return render(request, 'timetracking/entry_form.html', {
                'tickets': tickets,
                'preselected_ticket': ticket,
                'today': date_str or datetime.date.today().isoformat(),
                'post': request.POST,
                'entry': None,
            })

        TimeEntry.objects.create(
            user=request.user,
            jira_ticket=ticket,
            date=date,
            minutes=minutes,
            activity=activity,
        )
        messages.success(request, 'Entrada de tiempo registrada.')
        next_url = request.POST.get('next') or 'timetracking-list'
        if next_url.startswith('/'):
            return redirect(next_url)
        return redirect(next_url)


class TimeEntryEditView(LoginRequiredMixin, View):
    def _get_entry(self, request, pk):
        entry = get_object_or_404(TimeEntry, pk=pk)
        if entry.user != request.user:
            raise PermissionDenied
        return entry

    def get(self, request, pk):
        entry = self._get_entry(request, pk)
        tickets = JiraTicket.objects.order_by('issue_key')
        return render(request, 'timetracking/entry_form.html', {
            'entry': entry,
            'tickets': tickets,
            'preselected_ticket': entry.jira_ticket,
            'today': entry.date.isoformat(),
        })

    def post(self, request, pk):
        entry = self._get_entry(request, pk)
        issue_key = request.POST.get('jira_ticket', '').strip()
        date_str = request.POST.get('date', '').strip()
        minutes_str = request.POST.get('minutes', '').strip()
        activity = request.POST.get('activity', '').strip()

        errors = []
        ticket = JiraTicket.objects.filter(issue_key=issue_key).first()
        if not ticket:
            errors.append('Selecciona un ticket Jira válido.')
        try:
            date = datetime.date.fromisoformat(date_str)
        except ValueError:
            errors.append('Fecha inválida.')
            date = None
        try:
            minutes = int(minutes_str)
            if minutes <= 0:
                raise ValueError
        except ValueError:
            errors.append('Los minutos deben ser un número positivo.')
            minutes = None
        if not activity:
            errors.append('La actividad es obligatoria.')

        if errors:
            for e in errors:
                messages.error(request, e)
            tickets = JiraTicket.objects.order_by('issue_key')
            return render(request, 'timetracking/entry_form.html', {
                'entry': entry,
                'tickets': tickets,
                'preselected_ticket': ticket or entry.jira_ticket,
                'today': date_str,
                'post': request.POST,
            })

        entry.jira_ticket = ticket
        entry.date = date
        entry.minutes = minutes
        entry.activity = activity
        entry.save()
        messages.success(request, 'Entrada actualizada.')
        return redirect('timetracking-list')


class TimeEntryDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        entry = get_object_or_404(TimeEntry, pk=pk, user=request.user)
        entry.delete()
        messages.success(request, 'Entrada eliminada.')
        next_url = request.POST.get('next') or 'timetracking-list'
        if next_url.startswith('/'):
            return redirect(next_url)
        return redirect(next_url)


class DailyReportView(LoginRequiredMixin, View):
    def get(self, request):
        import datetime as dt_module
        from collections import defaultdict
        from django.utils import timezone
        from jira_integration.models import JiraEvent
        from itsm.models import TicketTag

        schedule = WorkSchedule.objects.filter(user=request.user).first()
        jira_username = schedule.jira_username.strip() if schedule and schedule.jira_username else ''
        try:
            jira_account_id = request.user.userprofile.jira_account_id.strip()
        except Exception:
            jira_account_id = ''

        _jira_configs = list(JiraStatusConfig.objects.all())
        if _jira_configs:
            _ip_statuses       = {c.status_name.lower() for c in _jira_configs if c.category == 'in_progress'}
            _terminal_statuses = {c.status_name.lower() for c in _jira_configs if c.category == 'done'}
        else:
            _ip_statuses       = {'in progress'}
            _terminal_statuses = {'done', 'descartado'}

        # --- Range ---
        range_param = request.GET.get('range', 'today')
        if range_param not in ('today', 'week', 'month', 'custom'):
            range_param = 'today'
        now = timezone.now()
        import zoneinfo as _zi
        try:
            user_tz = _zi.ZoneInfo(schedule.timezone) if schedule and schedule.timezone else dt_module.timezone.utc
        except Exception:
            user_tz = dt_module.timezone.utc
        now_local = now.astimezone(user_tz)

        custom_date_from = ''
        custom_date_to = ''

        if range_param == 'custom':
            try:
                custom_date_from = request.GET.get('date_from', '')
                df = dt_module.date.fromisoformat(custom_date_from)
            except ValueError:
                df = now_local.date()
                custom_date_from = df.isoformat()
                range_param = 'today'
            try:
                custom_date_to = request.GET.get('date_to', '')
                dt_val = dt_module.date.fromisoformat(custom_date_to)
            except ValueError:
                dt_val = df
                custom_date_to = dt_val.isoformat()
            if dt_val < df:
                dt_val = df
                custom_date_to = dt_val.isoformat()
            start_dt = dt_module.datetime(df.year, df.month, df.day, tzinfo=user_tz).astimezone(dt_module.timezone.utc)
            # end of range = end of date_to in user tz
            now = dt_module.datetime(dt_val.year, dt_val.month, dt_val.day,
                                     23, 59, 59, tzinfo=user_tz).astimezone(dt_module.timezone.utc)
            # cap to actual now so we don't show future
            actual_now = timezone.now()
            if now > actual_now:
                now = actual_now
        elif range_param == 'today':
            start_dt = now_local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_module.timezone.utc)
        elif range_param == 'week':
            start_dt = (now_local - dt_module.timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_module.timezone.utc)
        else:
            start_dt = (now_local - dt_module.timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt_module.timezone.utc)

        def range_seconds(entered_at, exited_at, ongoing_in_progress=False):
            """
            Count seconds from this segment that count toward the selected range.
            Only counts if the transition INTO this status happened within [start_dt, now],
            or if the segment is an ongoing In Progress that started before the range
            (the ticket is actively being worked on).
            """
            if not entered_at:
                return 0
            if entered_at >= start_dt:
                seg_end = min(exited_at or now, now)
                return max(0, int((seg_end - entered_at).total_seconds()))
            if ongoing_in_progress and exited_at is None:
                return max(0, int((now - start_dt).total_seconds()))
            return 0

        def fmt(seconds):
            seconds = max(0, int(seconds))
            hours, rem = divmod(seconds, 3600)
            minutes = rem // 60
            if hours:
                return f"{hours}h {minutes}m"
            return f"{minutes}m"

        my_tickets = []
        if jira_account_id or jira_username:
            qs = JiraTicket.objects.filter(is_deleted=False)
            if jira_account_id:
                qs = qs.filter(assignee_account_id=jira_account_id)
            else:
                qs = qs.filter(assignee__iexact=jira_username)
            my_tickets = list(qs.order_by('issue_key'))

        # Build raw segments per ticket (single event fetch)
        ticket_segments = {}
        for ticket in my_tickets:
            events = list(JiraEvent.objects.filter(ticket=ticket).order_by('received_at'))
            transitions = []
            for event in events:
                for item in event.payload.get('changelog', {}).get('items', []):
                    if item.get('field') == 'status':
                        transitions.append({
                            'from_status': item.get('fromString', ''),
                            'to_status': item.get('toString', ''),
                            'at': event.received_at,
                        })
            creation_event = next((e for e in events if e.event_type == 'jira:issue_created'), None)
            creation_time = creation_event.received_at if creation_event else (events[0].received_at if events else None)
            creation_status = (
                (creation_event.payload.get('issue', {}).get('fields', {}).get('status', {}).get('name', ''))
                if creation_event else ''
            )
            if not transitions:
                segs = [{'status': creation_status, 'entered_at': creation_time, 'exited_at': None}] if creation_status else []
                ticket_segments[ticket.issue_key] = segs
                continue
            initial_status = creation_status or transitions[0]['from_status']
            segs = [{'status': initial_status, 'entered_at': creation_time, 'exited_at': transitions[0]['at']}]
            for i, t in enumerate(transitions):
                exited_at = transitions[i + 1]['at'] if i + 1 < len(transitions) else None
                segs.append({'status': t['to_status'], 'entered_at': t['at'], 'exited_at': exited_at})
            ticket_segments[ticket.issue_key] = segs

        # Compute range seconds per segment, respecting the new semantics:
        # - segments entered within the range count normally
        # - ongoing In Progress segments entered before the range count from start_dt
        # - all other pre-range segments contribute 0
        def ticket_seg_secs(ticket):
            is_ip = ticket.status.lower() in _ip_statuses
            result = []
            for seg in ticket_segments[ticket.issue_key]:
                if not seg['status'] or not seg['entered_at']:
                    result.append(0)
                    continue
                ongoing_ip = is_ip and seg['exited_at'] is None
                result.append(range_seconds(seg['entered_at'], seg['exited_at'], ongoing_ip))
            return result

        # Per-ticket total range seconds (used for filtering and tag attribution)
        ticket_range_secs = {}
        ticket_seg_secs_map = {}
        for ticket in my_tickets:
            seg_secs = ticket_seg_secs(ticket)
            ticket_seg_secs_map[ticket.issue_key] = seg_secs
            ticket_range_secs[ticket.issue_key] = sum(seg_secs)

        # --- Filters (global — applied to all panels) ---
        selected_tags = request.GET.getlist('tags')
        selected_statuses = request.GET.getlist('statuses')

        # Collect all available tags from active tickets (before tag filter) for the UI
        active_keys_all = [k for k, v in ticket_range_secs.items() if v > 0]
        all_tags = sorted(set(
            tt.tag.name
            for tt in TicketTag.objects.filter(
                ticket__external_id__in=active_keys_all
            ).select_related('tag')
        ))

        _TERMINAL_STATUSES = _terminal_statuses
        _CATEGORY_ORDER = ['done', 'in_progress', 'blocked', 'testing', 'other', 'backlog']
        if _jira_configs:
            _STATUS_COLUMN_ORDER = []
            for _cat in _CATEGORY_ORDER:
                for _c in _jira_configs:
                    if _c.category == _cat:
                        _STATUS_COLUMN_ORDER.append(_c.status_name.lower())
        else:
            _STATUS_COLUMN_ORDER = [
                'done', 'in progress', 'bloqueado', 'testing',
                'selected for development', 'descartado', 'backlog',
            ]

        # Collect statuses: range-active for non-terminal, ever-reached for terminal
        all_statuses = []
        for ticket in my_tickets:
            for seg, secs in zip(ticket_segments[ticket.issue_key], ticket_seg_secs_map[ticket.issue_key]):
                if not seg['status'] or seg['status'] in all_statuses:
                    continue
                is_terminal = seg['status'].lower() in _TERMINAL_STATUSES
                if secs > 0 or (is_terminal and seg['entered_at']):
                    all_statuses.append(seg['status'])

        all_statuses.sort(key=lambda s: (
            _STATUS_COLUMN_ORDER.index(s.lower())
            if s.lower() in _STATUS_COLUMN_ORDER else len(_STATUS_COLUMN_ORDER)
        ))

        # Apply tag filter: keep only tickets that have ALL selected tags
        if selected_tags:
            tagged_per_tag = []
            for tag_name in selected_tags:
                keys = set(TicketTag.objects.filter(
                    ticket__external_id__in=active_keys_all,
                    tag__name=tag_name,
                ).values_list('ticket__external_id', flat=True))
                tagged_per_tag.append(keys)
            # AND: intersection of all tag sets
            matching_keys = set.intersection(*tagged_per_tag) if tagged_per_tag else set(active_keys_all)
            filtered_tickets = [t for t in my_tickets if t.issue_key in matching_keys]
        else:
            filtered_tickets = [t for t in my_tickets if ticket_range_secs.get(t.issue_key, 0) > 0]

        # Apply status filter: keep only tickets with activity in at least one selected status
        if selected_statuses:
            filtered_tickets = [
                t for t in filtered_tickets
                if any(
                    seg['status'] in selected_statuses and secs > 0
                    for seg, secs in zip(ticket_segments[t.issue_key], ticket_seg_secs_map[t.issue_key])
                )
            ]

        # Sort by most recently updated (latest JiraEvent) descending
        if filtered_tickets:
            from django.db.models import Max
            latest_event = {
                row['ticket_id']: row['latest']
                for row in JiraEvent.objects.filter(
                    ticket__in=filtered_tickets
                ).values('ticket_id').annotate(latest=Max('received_at'))
            }
            filtered_tickets.sort(key=lambda t: latest_event.get(t.pk), reverse=True)

        # --- Time by Status (range-scoped, filters applied) ---
        status_seconds = defaultdict(int)
        for ticket in filtered_tickets:
            segs = ticket_segments[ticket.issue_key]
            for seg, secs in zip(segs, ticket_seg_secs_map[ticket.issue_key]):
                if seg['status'] and secs > 0:
                    status_seconds[seg['status']] += secs

        status_totals = [
            {'status': s, 'secs': secs, 'display': fmt(secs)}
            for s, secs in sorted(status_seconds.items())
            if secs > 0
        ]

        # --- Time by Tag (In Progress only, transitions that started within the range) ---
        # Using all-status time inflates weekly/monthly totals because N concurrent tickets
        # each contribute the full range duration. Only IP segments with entered_at >= start_dt
        # are counted — ongoing IP from before the range contributes 0 here.
        ticket_ip_range_secs = {}
        for ticket in my_tickets:
            segs = ticket_segments[ticket.issue_key]
            secs = sum(
                max(0, int((min(seg['exited_at'] or now, now) - seg['entered_at']).total_seconds()))
                for seg in segs
                if seg['status']
                and seg['status'].lower() in _ip_statuses
                and seg['entered_at']
                and seg['entered_at'] >= start_dt
            )
            ticket_ip_range_secs[ticket.issue_key] = secs

        filtered_keys = [t.issue_key for t in filtered_tickets]
        tag_seconds = defaultdict(int)
        for tt in TicketTag.objects.filter(
            ticket__external_id__in=filtered_keys
        ).select_related('tag', 'ticket'):
            secs = ticket_ip_range_secs.get(tt.ticket.external_id, 0)
            if secs > 0:
                tag_seconds[tt.tag.name] += secs
        tag_totals = [
            {'tag': name, 'secs': secs, 'display': fmt(secs)}
            for name, secs in sorted(tag_seconds.items(), key=lambda x: -x[1])
            if secs > 0
        ]

        # --- In Progress / Now (unaffected by range or tag filter) ---
        def _extract_body(body):
            if isinstance(body, str):
                return body
            if isinstance(body, dict):
                texts = []
                def _walk(node):
                    if isinstance(node, dict):
                        if node.get('type') == 'text':
                            texts.append(node.get('text', ''))
                        for child in node.get('content', []):
                            _walk(child)
                _walk(body)
                return ' '.join(t for t in texts if t).strip()
            return ''

        ip_tickets = [t for t in my_tickets if t.status.lower() in _ip_statuses]
        ip_last_comment = {}
        if ip_tickets:
            for event in JiraEvent.objects.filter(
                ticket_id__in=[t.pk for t in ip_tickets]
            ).order_by('-received_at'):
                if event.ticket_id in ip_last_comment:
                    continue
                comment = event.payload.get('comment') or {}
                if comment:
                    author = (comment.get('author') or {}).get('displayName') or ''
                    body = _extract_body(comment.get('body', ''))
                    if body:
                        ip_last_comment[event.ticket_id] = {'author': author, 'body': body}

        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_rows = []
        for ticket in my_tickets:
            segs = ticket_segments[ticket.issue_key]
            # Primary check: ticket.status field. Fallback: ongoing segment status, which
            # stays correct even when ticket.status is stale due to out-of-order webhook events
            # (e.g. jira:issue_created arriving after jira:issue_updated rolls back the status).
            is_ip = ticket.status.lower() in _ip_statuses or any(
                seg['status'] and seg['status'].lower() in _ip_statuses and seg['exited_at'] is None
                for seg in segs
            )
            if not is_ip:
                continue
            ongoing_seg = next(
                (seg for seg in segs if seg['entered_at'] and seg['exited_at'] is None),
                None,
            )
            if ongoing_seg:
                total_secs = int((now - ongoing_seg['entered_at']).total_seconds())
            else:
                total_secs = 0
            today_ip_secs = sum(
                max(0, int((min(seg['exited_at'] or now, now) - max(seg['entered_at'], today_start)).total_seconds()))
                for seg in segs
                if seg['status'] and seg['status'].lower() in _ip_statuses
                and seg['entered_at'] and min(seg['exited_at'] or now, now) > max(seg['entered_at'], today_start)
            )
            today_rows.append({
                'ticket': ticket,
                'jira_ongoing': fmt(total_secs) if ongoing_seg else '—',
                'jira_today': fmt(today_ip_secs),
                'last_message': ip_last_comment.get(ticket.pk),
                'parent': None,
            })

        # Resolve parent tickets for envelope grouping
        _parent_keys = {r['ticket'].parent_key for r in today_rows if r['ticket'].parent_key}
        _parent_map = {}
        if _parent_keys:
            for _pt in JiraTicket.objects.filter(issue_key__in=_parent_keys):
                _parent_map[_pt.issue_key] = _pt
        for row in today_rows:
            _pk = row['ticket'].parent_key
            if _pk:
                row['parent'] = _parent_map.get(_pk)

        # Suppress parent tickets that are already shown as envelope headers
        today_rows = [r for r in today_rows if r['ticket'].issue_key not in _parent_keys]

        # Alert: count logical groups, not raw tickets
        _ip_groups = set()
        for row in today_rows:
            if row['parent']:
                _ip_groups.add(('parent', row['ticket'].parent_key))
            else:
                _ip_groups.add(('standalone', row['ticket'].issue_key))
        _today_rows_alert = len(_ip_groups) > 1

        # --- Status history pivot (range-scoped, filters applied) ---
        pivot_rows = []
        for ticket in filtered_tickets:
            by_status = defaultdict(lambda: {'secs': 0, 'ongoing': False, 'last_entered': None})
            segs = ticket_segments[ticket.issue_key]
            for seg, secs in zip(segs, ticket_seg_secs_map[ticket.issue_key]):
                if not seg['status'] or not seg['entered_at']:
                    continue
                is_terminal = seg['status'].lower() in _TERMINAL_STATUSES
                if is_terminal:
                    prev = by_status[seg['status']]['last_entered']
                    if prev is None or seg['entered_at'] > prev:
                        by_status[seg['status']]['last_entered'] = seg['entered_at']
                elif secs > 0:
                    by_status[seg['status']]['secs'] += secs
                    if seg['exited_at'] is None:
                        by_status[seg['status']]['ongoing'] = True
            cells = []
            for status in all_statuses:
                entry = by_status.get(status)
                is_terminal = status.lower() in _TERMINAL_STATUSES
                if is_terminal:
                    entered_at = entry['last_entered'] if entry else None
                    ts = entered_at.astimezone(user_tz) if entered_at else None
                    cells.append({'is_terminal': True, 'timestamp': ts, 'duration': None, 'ongoing': False})
                else:
                    if entry and entry['secs'] > 0:
                        cells.append({'is_terminal': False, 'timestamp': None, 'duration': fmt(entry['secs']), 'ongoing': entry['ongoing']})
                    else:
                        cells.append({'is_terminal': False, 'timestamp': None, 'duration': '—', 'ongoing': False})
            pivot_rows.append({'ticket': ticket, 'cells': cells})

        # Group pivot_rows by parent_key for Status History tree rendering
        _pivot_child_pkeys = {r['ticket'].parent_key for r in pivot_rows if r['ticket'].parent_key}
        _pivot_parent_ticket_map = {}
        if _pivot_child_pkeys:
            for _ppt in JiraTicket.objects.filter(issue_key__in=_pivot_child_pkeys):
                _pivot_parent_ticket_map[_ppt.issue_key] = _ppt

        _pivot_row_by_key = {r['ticket'].issue_key: r for r in pivot_rows}
        _pivot_children_by_parent = {}
        for row in pivot_rows:
            pk = row['ticket'].parent_key
            if pk and pk in _pivot_parent_ticket_map:
                _pivot_children_by_parent.setdefault(pk, []).append(row)

        _pivot_in_group = set()
        pivot_groups = []
        for pk, children in _pivot_children_by_parent.items():
            pivot_groups.append({
                'parent_ticket': _pivot_parent_ticket_map[pk],
                'parent_row': _pivot_row_by_key.get(pk),
                'children': children,
                'standalone': None,
            })
            _pivot_in_group.add(pk)
            for r in children:
                _pivot_in_group.add(r['ticket'].issue_key)

        for row in pivot_rows:
            if row['ticket'].issue_key not in _pivot_in_group:
                pivot_groups.append({
                    'parent_ticket': None,
                    'parent_row': None,
                    'children': [],
                    'standalone': row,
                })

        # --- Closed tickets panel ---
        closed_tickets_raw = []
        for row in pivot_rows:
            closed_at = None
            for seg in ticket_segments[row['ticket'].issue_key]:
                if not seg['status'] or not seg['entered_at']:
                    continue
                if seg['status'].lower() not in _TERMINAL_STATUSES:
                    continue
                if start_dt <= seg['entered_at'] <= now:
                    if closed_at is None or seg['entered_at'] > closed_at:
                        closed_at = seg['entered_at']
            if closed_at is None:
                continue
            ip_secs = sum(
                secs
                for seg, secs in zip(ticket_segments[row['ticket'].issue_key], ticket_seg_secs_map[row['ticket'].issue_key])
                if seg['status'] and seg['status'].lower() in _ip_statuses
            )
            closed_tickets_raw.append({
                'ticket': row['ticket'],
                'closed_at': closed_at.astimezone(user_tz),
                'ip_time': fmt(ip_secs) if ip_secs > 0 else None,
            })

        closed_tickets_raw.sort(key=lambda x: x['closed_at'], reverse=True)

        _closed_child_pkeys = {r['ticket'].parent_key for r in closed_tickets_raw if r['ticket'].parent_key}
        _closed_parent_ticket_map = {}
        if _closed_child_pkeys:
            for _cpt in JiraTicket.objects.filter(issue_key__in=_closed_child_pkeys):
                _closed_parent_ticket_map[_cpt.issue_key] = _cpt

        _closed_children_by_parent = {}
        for row in closed_tickets_raw:
            pk = row['ticket'].parent_key
            if pk and pk in _closed_parent_ticket_map:
                _closed_children_by_parent.setdefault(pk, []).append(row)

        _closed_in_group = set()
        closed_groups = []
        for pk, children in _closed_children_by_parent.items():
            closed_groups.append({
                'parent_ticket': _closed_parent_ticket_map[pk],
                'children': children,
                'standalone': None,
            })
            _closed_in_group.add(pk)
            for r in children:
                _closed_in_group.add(r['ticket'].issue_key)

        for row in closed_tickets_raw:
            if row['ticket'].issue_key not in _closed_in_group:
                closed_groups.append({
                    'parent_ticket': None,
                    'children': [],
                    'standalone': row,
                })

        # --- Gantt timeline ---
        _category_colors = {
            'in_progress': '#0d6efd',
            'blocked':     '#dc3545',
            'done':        '#198754',
            'testing':     '#fd7e14',
            'backlog':     '#6c757d',
            'other':       '#6c757d',
        }
        if _jira_configs:
            _status_colors = {
                c.status_name.lower(): _category_colors.get(c.category, '#6c757d')
                for c in _jira_configs
            }
        else:
            _status_colors = {
                'in progress': '#0d6efd', 'en curso': '#0d6efd',
                'bloqueado': '#dc3545', 'blocked': '#dc3545',
                'done': '#198754', 'backlog': '#6c757d',
                'testing': '#fd7e14', 'in review': '#6f42c1', 'review': '#6f42c1',
            }
        _fallback_colors = ['#20c997', '#0dcaf0', '#ffc107', '#d63384', '#adb5bd']
        _fallback_idx = {}

        def status_color(s):
            key = s.lower()
            if key in _status_colors:
                return _status_colors[key]
            if key not in _fallback_idx:
                _fallback_idx[key] = len(_fallback_idx) % len(_fallback_colors)
            return _fallback_colors[_fallback_idx[key]]

        if status_totals:
            _max_status_secs = max(r['secs'] for r in status_totals)
            for r in status_totals:
                r['pct'] = round(r['secs'] / _max_status_secs * 100) if _max_status_secs else 0
                r['color'] = status_color(r['status'])
        if tag_totals:
            _max_tag_secs = max(r['secs'] for r in tag_totals)
            for r in tag_totals:
                r['pct'] = round(r['secs'] / _max_tag_secs * 100) if _max_tag_secs else 0

        range_total_secs = max(1, (now - start_dt).total_seconds())

        def bar_pos(entered_at, exited_at):
            eff_start = max(entered_at, start_dt)
            eff_end = min(exited_at or now, now)
            left = max(0.0, (eff_start - start_dt).total_seconds() / range_total_secs * 100)
            width = max(0.0, (eff_end - eff_start).total_seconds() / range_total_secs * 100)
            return round(left, 3), round(width, 3)

        _terminal_statuses = _TERMINAL_STATUSES

        gantt_rows = []
        for ticket in filtered_tickets:
            bars = []
            for seg in ticket_segments[ticket.issue_key]:
                if not seg['entered_at'] or not seg['status']:
                    continue
                is_terminal = seg['status'].lower() in _terminal_statuses
                if seg['exited_at'] is None and is_terminal:
                    continue
                # When status filter is active, only render bars for selected statuses
                if selected_statuses and seg['status'] not in selected_statuses:
                    continue
                exited = seg['exited_at'] or now
                if seg['entered_at'] >= now or exited <= start_dt:
                    continue
                left, width = bar_pos(seg['entered_at'], seg['exited_at'])
                if width < 0.05:
                    continue
                bars.append({
                    'status': seg['status'],
                    'color': status_color(seg['status']),
                    'left': left,
                    'width': width,
                    'ongoing': seg['exited_at'] is None,
                })
            if bars:
                gantt_rows.append({'ticket': ticket, 'bars': bars})

        # X axis ticks
        # Gantt tick strategy: today or single-day custom → hourly; week or multi-day custom → daily; month → every 3 days
        _custom_single_day = (range_param == 'custom' and custom_date_from == custom_date_to)
        _custom_multi_day = (range_param == 'custom' and custom_date_from != custom_date_to)
        _range_days = max(1, (now - start_dt).days)

        gantt_ticks = []
        if range_param == 'today' or _custom_single_day:
            tick = start_dt
            while tick <= now:
                left = (tick - start_dt).total_seconds() / range_total_secs * 100
                gantt_ticks.append({'label': tick.astimezone(user_tz).strftime('%H:%M'), 'left': round(left, 2)})
                tick += datetime.timedelta(hours=2)
        elif range_param == 'week' or _custom_multi_day:
            tick = start_dt
            while tick <= now:
                left = (tick - start_dt).total_seconds() / range_total_secs * 100
                gantt_ticks.append({'label': tick.astimezone(user_tz).strftime('%a %d'), 'left': round(left, 2)})
                tick += datetime.timedelta(days=1)
        else:
            tick = start_dt
            while tick <= now:
                left = (tick - start_dt).total_seconds() / range_total_secs * 100
                gantt_ticks.append({'label': tick.astimezone(user_tz).strftime('%d/%m'), 'left': round(left, 2)})
                tick += datetime.timedelta(days=3)

        # Working hour boundary lines on the Gantt (dashed vertical lines at start/end of each working day)
        work_lines = []
        if schedule and schedule.start_time and schedule.end_time:
            _weekday_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
            d = start_dt.astimezone(user_tz).date()
            end_date = now.astimezone(user_tz).date()
            while d <= end_date:
                if getattr(schedule, _weekday_map[d.weekday()], False):
                    ws = dt_module.datetime(d.year, d.month, d.day,
                                            schedule.start_time.hour, schedule.start_time.minute,
                                            tzinfo=user_tz).astimezone(dt_module.timezone.utc)
                    we = dt_module.datetime(d.year, d.month, d.day,
                                            schedule.end_time.hour, schedule.end_time.minute,
                                            tzinfo=user_tz).astimezone(dt_module.timezone.utc)
                    if start_dt <= ws <= now:
                        left = (ws - start_dt).total_seconds() / range_total_secs * 100
                        work_lines.append({'left': round(left, 3)})
                    if start_dt <= we <= now:
                        left = (we - start_dt).total_seconds() / range_total_secs * 100
                        work_lines.append({'left': round(left, 3)})
                d += dt_module.timedelta(days=1)

        # Color legend (unique statuses across all gantt bars)
        seen = {}
        for row in gantt_rows:
            for bar in row['bars']:
                if bar['status'] not in seen:
                    seen[bar['status']] = bar['color']
        gantt_legend = [{'status': s, 'color': c} for s, c in seen.items()]

        # Group gantt_rows by parent_key for tree rendering in the Gantt Timeline
        _gantt_child_pkeys = {r['ticket'].parent_key for r in gantt_rows if r['ticket'].parent_key}
        _gantt_parent_ticket_map = {}
        if _gantt_child_pkeys:
            for _gpt in JiraTicket.objects.filter(issue_key__in=_gantt_child_pkeys):
                _gantt_parent_ticket_map[_gpt.issue_key] = _gpt

        _gantt_row_by_key = {r['ticket'].issue_key: r for r in gantt_rows}
        _children_by_parent = {}
        for row in gantt_rows:
            pk = row['ticket'].parent_key
            if pk and pk in _gantt_parent_ticket_map:
                _children_by_parent.setdefault(pk, []).append(row)

        _gantt_in_group = set()
        gantt_groups = []
        for pk, children in _children_by_parent.items():
            gantt_groups.append({
                'parent_ticket': _gantt_parent_ticket_map[pk],
                'parent_row': _gantt_row_by_key.get(pk),
                'children': children,
                'standalone': None,
            })
            _gantt_in_group.add(pk)
            for r in children:
                _gantt_in_group.add(r['ticket'].issue_key)

        for row in gantt_rows:
            if row['ticket'].issue_key not in _gantt_in_group:
                gantt_groups.append({
                    'parent_ticket': None,
                    'parent_row': None,
                    'children': [],
                    'standalone': row,
                })

        # --- In Progress bar (uses same range as the report) ---
        actual_now = timezone.now()
        bar_start = start_dt
        bar_end = min(now, actual_now)
        bar_total_secs = max(1, (bar_end - bar_start).total_seconds())
        bar_days = bar_total_secs / 86400

        # Collect IP intervals with contributing tickets (before merging)
        _day_attrs = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']
        raw_ip = []
        for ticket in my_tickets:
            for seg in ticket_segments[ticket.issue_key]:
                if not seg['status'] or seg['status'].lower() not in _ip_statuses:
                    continue
                if not seg['entered_at']:
                    continue
                seg_s = max(seg['entered_at'], bar_start)
                seg_e = min(seg['exited_at'] or actual_now, bar_end)
                if seg_e > seg_s:
                    raw_ip.append((seg_s, seg_e, ticket))

        # Merge overlapping intervals, tracking which tickets contribute to each
        raw_ip.sort(key=lambda x: x[0])
        merged_ip = []
        for seg_s, seg_e, ticket in raw_ip:
            if merged_ip and seg_s <= merged_ip[-1]['end']:
                merged_ip[-1]['end'] = max(merged_ip[-1]['end'], seg_e)
                if ticket not in merged_ip[-1]['tickets']:
                    merged_ip[-1]['tickets'].append(ticket)
            else:
                merged_ip.append({'start': seg_s, 'end': seg_e, 'tickets': [ticket]})

        def _pct(dt_val):
            return round((dt_val - bar_start).total_seconds() / bar_total_secs * 100, 3)

        daily_ip_bars = [
            {
                'left': _pct(m['start']),
                'width': round((m['end'] - m['start']).total_seconds() / bar_total_secs * 100, 3),
                'tooltip': '&#10;'.join(f"{t.issue_key}: {t.title}" for t in m['tickets']),
            }
            for m in merged_ip
        ]

        ip_raw_bars = [
            {
                'start': int(m['start'].timestamp() * 1000),
                'end':   int(m['end'].timestamp() * 1000),
                'tooltip': '\n'.join(f"{t.issue_key}: {t.title}" for t in m['tickets']),
            }
            for m in merged_ip
        ]

        # Brackets above the IP bar: one bracket per consecutive run of the same parent.
        # Covers all my_tickets (not just currently-active) so historical segments get brackets.
        # When parent changes, the current bracket closes and a new one opens.
        _all_parent_keys_set = {t.parent_key for t in my_tickets if t.parent_key}
        _all_parent_map = {}
        if _all_parent_keys_set:
            for _pt in JiraTicket.objects.filter(issue_key__in=_all_parent_keys_set):
                _all_parent_map[_pt.issue_key] = _pt

        _all_ip_segs = []
        for ticket in my_tickets:
            if not ticket.parent_key or ticket.parent_key not in _all_parent_map:
                continue
            for seg in ticket_segments[ticket.issue_key]:
                if not seg['status'] or seg['status'].lower() not in _ip_statuses or not seg['entered_at']:
                    continue
                seg_s = max(seg['entered_at'], bar_start)
                seg_e = min(seg['exited_at'] or actual_now, bar_end)
                if seg_e > seg_s:
                    _all_ip_segs.append((seg_s, seg_e, ticket.parent_key))

        _all_ip_segs.sort(key=lambda x: x[0])

        ip_brackets = []
        ip_raw_brackets = []
        if _all_ip_segs:
            _run_pk = _all_ip_segs[0][2]
            _run_s = _all_ip_segs[0][0]
            _run_e = _all_ip_segs[0][1]
            for _seg_s, _seg_e, _pk in _all_ip_segs[1:]:
                if _pk == _run_pk:
                    _run_e = max(_run_e, _seg_e)
                else:
                    ip_brackets.append({
                        'left': round((_run_s - bar_start).total_seconds() / bar_total_secs * 100, 3),
                        'width': round((_run_e - _run_s).total_seconds() / bar_total_secs * 100, 3),
                        'label': _run_pk,
                    })
                    ip_raw_brackets.append({
                        'start': int(_run_s.timestamp() * 1000),
                        'end':   int(_run_e.timestamp() * 1000),
                        'label': _run_pk,
                    })
                    _run_pk = _pk
                    _run_s = _seg_s
                    _run_e = _seg_e
            ip_brackets.append({
                'left': round((_run_s - bar_start).total_seconds() / bar_total_secs * 100, 3),
                'width': round((_run_e - _run_s).total_seconds() / bar_total_secs * 100, 3),
                'label': _run_pk,
            })
            ip_raw_brackets.append({
                'start': int(_run_s.timestamp() * 1000),
                'end':   int(_run_e.timestamp() * 1000),
                'label': _run_pk,
            })

        # Off-hours shading: iterate each calendar day in range
        daily_off_shades = []
        ip_raw_shades = []
        day_cursor = bar_start.astimezone(user_tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        while day_cursor.astimezone(dt_module.timezone.utc) < bar_end:
            day_utc = day_cursor.astimezone(dt_module.timezone.utc)
            next_day_utc = (day_cursor + dt_module.timedelta(days=1)).astimezone(dt_module.timezone.utc)
            weekday_attr = _day_attrs[day_cursor.weekday()]
            is_work_day = getattr(schedule, weekday_attr) if schedule else True

            if is_work_day and schedule:
                work_start_local = day_cursor.replace(
                    hour=schedule.start_time.hour,
                    minute=schedule.start_time.minute,
                    second=0, microsecond=0,
                )
                work_end_local = day_cursor.replace(
                    hour=schedule.end_time.hour,
                    minute=schedule.end_time.minute,
                    second=0, microsecond=0,
                )
                work_s = work_start_local.astimezone(dt_module.timezone.utc)
                work_e = work_end_local.astimezone(dt_module.timezone.utc)

                # Before work hours
                shade_s = max(day_utc, bar_start)
                shade_e = min(work_s, bar_end)
                if shade_e > shade_s:
                    daily_off_shades.append({'left': _pct(shade_s), 'width': round((shade_e - shade_s).total_seconds() / bar_total_secs * 100, 3)})
                    ip_raw_shades.append({'start': int(shade_s.timestamp() * 1000), 'end': int(shade_e.timestamp() * 1000)})

                # After work hours
                shade_s = max(work_e, bar_start)
                shade_e = min(next_day_utc, bar_end)
                if shade_e > shade_s:
                    daily_off_shades.append({'left': _pct(shade_s), 'width': round((shade_e - shade_s).total_seconds() / bar_total_secs * 100, 3)})
                    ip_raw_shades.append({'start': int(shade_s.timestamp() * 1000), 'end': int(shade_e.timestamp() * 1000)})
            else:
                # Non-working day: entire day shaded
                shade_s = max(day_utc, bar_start)
                shade_e = min(next_day_utc, bar_end)
                if shade_e > shade_s:
                    daily_off_shades.append({'left': _pct(shade_s), 'width': round((shade_e - shade_s).total_seconds() / bar_total_secs * 100, 3)})
                    ip_raw_shades.append({'start': int(shade_s.timestamp() * 1000), 'end': int(shade_e.timestamp() * 1000)})

            day_cursor += dt_module.timedelta(days=1)

        # Ticks
        if bar_days <= 1:
            tick_delta = dt_module.timedelta(hours=2)
            tick_fmt = '%H:%M'
        elif bar_days <= 7:
            tick_delta = dt_module.timedelta(days=1)
            tick_fmt = '%d/%m'
        else:
            tick_delta = dt_module.timedelta(days=7)
            tick_fmt = '%d/%m'

        daily_ticks = []
        tick_dt = bar_start + tick_delta
        while tick_dt < bar_end:
            daily_ticks.append({'left': round(_pct(tick_dt), 3), 'label': tick_dt.astimezone(user_tz).strftime(tick_fmt)})
            tick_dt += tick_delta

        if schedule and schedule.start_time and schedule.end_time:
            _bar_end_local = bar_end.astimezone(user_tz)
            _wh_s = _bar_end_local.replace(
                hour=schedule.start_time.hour, minute=schedule.start_time.minute,
                second=0, microsecond=0,
            ).astimezone(dt_module.timezone.utc)
            _wh_e = _bar_end_local.replace(
                hour=schedule.end_time.hour, minute=schedule.end_time.minute,
                second=0, microsecond=0,
            ).astimezone(dt_module.timezone.utc)
            _wh_start_ms = int(_wh_s.timestamp() * 1000)
            _wh_end_ms = int(_wh_e.timestamp() * 1000)
        else:
            _wh_start_ms = None
            _wh_end_ms = None

        _ip_json_raw = json.dumps({
            'bars': ip_raw_bars,
            'brackets': ip_raw_brackets,
            'shades': ip_raw_shades,
            'barStart': int(bar_start.timestamp() * 1000),
            'barEnd': int(bar_end.timestamp() * 1000),
            'tzName': (schedule.timezone if schedule and schedule.timezone else 'UTC'),
            'whStart': _wh_start_ms,
            'whEnd': _wh_end_ms,
        }) if daily_ip_bars else ''
        # Escape HTML-sensitive chars so output is safe with |safe in the template.
        # Uses JSON-valid unicode escapes — JSON.parse() decodes them back correctly.
        ip_bar_json = _ip_json_raw.replace('&', '\\u0026').replace('<', '\\u003C').replace('>', '\\u003E')

        return render(request, 'timetracking/report.html', {
            'status_totals': status_totals,
            'today_rows': today_rows,
            'today_rows_alert': _today_rows_alert,
            'pivot_rows': pivot_rows,
            'pivot_groups': pivot_groups,
            'closed_groups': closed_groups,
            'all_statuses': all_statuses,
            'jira_username': jira_username,
            'jira_account_id': jira_account_id,
            'range_param': range_param,
            'tag_totals': tag_totals,
            'selected_tags': selected_tags,
            'all_tags': all_tags,
            'selected_statuses': selected_statuses,
            'gantt_rows': gantt_rows,
            'gantt_groups': gantt_groups,
            'gantt_ticks': gantt_ticks,
            'gantt_legend': gantt_legend,
            'work_lines': work_lines,
            'custom_date_from': custom_date_from,
            'custom_date_to': custom_date_to,
            'daily_ip_bars': daily_ip_bars,
            'ip_brackets': ip_brackets,
            'daily_off_shades': daily_off_shades,
            'daily_ticks': daily_ticks,
            'ip_bar_json': ip_bar_json,
        })


class WorkScheduleView(LoginRequiredMixin, View):
    DAYS = [
        ('mon', 'Monday'),
        ('tue', 'Tuesday'),
        ('wed', 'Wednesday'),
        ('thu', 'Thursday'),
        ('fri', 'Friday'),
        ('sat', 'Saturday'),
        ('sun', 'Sunday'),
    ]

    def _get_or_create(self, user):
        schedule, _ = WorkSchedule.objects.get_or_create(user=user)
        return schedule

    def get(self, request):
        return redirect('settings-user')

    def post(self, request):
        schedule = self._get_or_create(request.user)
        for attr, _ in self.DAYS:
            setattr(schedule, attr, attr in request.POST)
        schedule.jira_username = request.POST.get('jira_username', '').strip()
        tz = request.POST.get('timezone', 'UTC').strip() or 'UTC'
        try:
            import zoneinfo
            zoneinfo.ZoneInfo(tz)
            schedule.timezone = tz
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            messages.error(request, f'Invalid timezone: {tz}')
            return self._render(request, schedule)
        start = request.POST.get('start_time', '').strip()
        end = request.POST.get('end_time', '').strip()
        import datetime as dt
        try:
            schedule.start_time = dt.time.fromisoformat(start)
        except ValueError:
            messages.error(request, 'Hora de inicio inválida.')
            return self._render(request, schedule)
        try:
            schedule.end_time = dt.time.fromisoformat(end)
        except ValueError:
            messages.error(request, 'Hora de fin inválida.')
            return self._render(request, schedule)
        if schedule.start_time >= schedule.end_time:
            messages.error(request, 'La hora de fin debe ser posterior a la de inicio.')
            return self._render(request, schedule)
        schedule.save()
        messages.success(request, 'Horario guardado.')
        return redirect('settings-user')

    def _render(self, request, schedule):
        active_days = {attr for attr, _ in self.DAYS if getattr(schedule, attr)}
        return render(request, 'timetracking/schedule_form.html', {
            'schedule': schedule,
            'days': self.DAYS,
            'active_days': active_days,
        })


class TicketTimelineView(LoginRequiredMixin, View):
    def get(self, request, issue_key):
        import datetime as dt_module
        import zoneinfo as _zi
        from collections import defaultdict
        from django.utils import timezone

        ticket = get_object_or_404(JiraTicket, issue_key=issue_key)

        schedule = WorkSchedule.objects.filter(user=request.user).first()
        try:
            user_tz = _zi.ZoneInfo(schedule.timezone) if schedule and schedule.timezone else _zi.ZoneInfo('UTC')
        except Exception:
            user_tz = _zi.ZoneInfo('UTC')

        now = timezone.now()
        today_local = now.astimezone(user_tz).date()

        date_from_str = request.GET.get('date_from', '')
        date_to_str = request.GET.get('date_to', '')
        try:
            date_from = dt_module.date.fromisoformat(date_from_str)
        except ValueError:
            date_from = today_local
        try:
            date_to = dt_module.date.fromisoformat(date_to_str)
        except ValueError:
            date_to = today_local

        if date_to < date_from:
            date_to = date_from

        # Convert local date range to UTC-aware boundaries
        start_dt = dt_module.datetime(date_from.year, date_from.month, date_from.day,
                                      tzinfo=user_tz).astimezone(dt_module.timezone.utc)
        end_dt = dt_module.datetime(date_to.year, date_to.month, date_to.day,
                                    tzinfo=user_tz) + dt_module.timedelta(days=1)
        end_dt = end_dt.astimezone(dt_module.timezone.utc)

        # Fetch all Jira events for this ticket (all time — needed to compute status durations)
        all_events = list(JiraEvent.objects.filter(ticket=ticket).order_by('received_at'))

        def fmt(seconds):
            seconds = max(0, int(seconds))
            h, rem = divmod(seconds, 3600)
            m = rem // 60
            if h:
                return f"{h}h {m}m"
            return f"{m}m"

        # Build status segments across all time (for duration calculation)
        raw_transitions = []
        for event in all_events:
            for item in event.payload.get('changelog', {}).get('items', []):
                if item.get('field') == 'status':
                    raw_transitions.append({'to_status': item.get('toString', ''), 'at': event.received_at})

        segments = {}  # entered_at → {status, exited_at}
        for i, t in enumerate(raw_transitions):
            exited_at = raw_transitions[i + 1]['at'] if i + 1 < len(raw_transitions) else None
            segments[t['at']] = {'status': t['to_status'], 'exited_at': exited_at}

        def _adf_to_text(body):
            if isinstance(body, str):
                return body
            if not isinstance(body, dict):
                return ''
            texts = []
            def _walk(node):
                if isinstance(node, dict):
                    if node.get('type') == 'text':
                        texts.append(node.get('text', ''))
                    for child in node.get('content', []):
                        _walk(child)
            _walk(body)
            return ' '.join(t for t in texts if t).strip()

        # Build timeline: all activity events within the date range
        timeline = []
        status_seconds = defaultdict(int)

        for event in all_events:
            if event.received_at < start_dt or event.received_at >= end_dt:
                continue
            at_local = event.received_at.astimezone(user_tz)
            items = event.payload.get('changelog', {}).get('items', [])
            for item in items:
                field = item.get('field', '')
                if field == 'status':
                    seg = segments.get(event.received_at)
                    if seg:
                        exited = seg['exited_at'] or now
                        effective_start = max(event.received_at, start_dt)
                        effective_end = min(exited, now)
                        secs = max(0, int((effective_end - effective_start).total_seconds()))
                        ongoing = seg['exited_at'] is None
                        status_seconds[seg['status']] += secs
                        timeline.append({
                            'type': 'transition',
                            'at': at_local,
                            'from_status': item.get('fromString', ''),
                            'status': seg['status'],
                            'duration': fmt(secs),
                            'ongoing': ongoing,
                            'sort_key': event.received_at,
                        })
                else:
                    from_val = item.get('fromString') or item.get('from') or ''
                    to_val = item.get('toString') or item.get('to') or ''
                    timeline.append({
                        'type': 'activity',
                        'at': at_local,
                        'field': field,
                        'from_val': from_val,
                        'to_val': to_val,
                        'sort_key': event.received_at,
                    })
            comment = event.payload.get('comment') or {}
            if comment:
                author_obj = comment.get('author') or {}
                author = author_obj.get('displayName') or author_obj.get('name') or ''
                body = _adf_to_text(comment.get('body', ''))
                if body:
                    timeline.append({
                        'type': 'comment',
                        'at': at_local,
                        'author': author,
                        'body': body,
                        'sort_key': event.received_at,
                    })

        # Fetch manual TimeEntry records in the date range
        manual_entries = list(
            TimeEntry.objects.filter(
                user=request.user,
                jira_ticket=ticket,
                date__gte=date_from,
                date__lte=date_to,
            ).order_by('date', 'created_at')
        )
        total_manual_minutes = 0
        for entry in manual_entries:
            total_manual_minutes += entry.minutes
            timeline.append({
                'type': 'manual',
                'at': dt_module.datetime(entry.date.year, entry.date.month, entry.date.day, tzinfo=user_tz),
                'entry': entry,
                'sort_key': dt_module.datetime(entry.date.year, entry.date.month, entry.date.day,
                                               tzinfo=user_tz).astimezone(dt_module.timezone.utc),
            })

        timeline.sort(key=lambda x: x['sort_key'], reverse=True)
        comments = [e for e in timeline if e['type'] == 'comment']

        # All-time comments for Last Message card (ignores date range)
        all_comments = []
        for event in all_events:
            comment = event.payload.get('comment') or {}
            if comment:
                author_obj = comment.get('author') or {}
                author = author_obj.get('displayName') or author_obj.get('name') or ''
                body = _adf_to_text(comment.get('body', ''))
                if body:
                    all_comments.append({
                        'at': event.received_at.astimezone(user_tz),
                        'author': author,
                        'body': body,
                        'sort_key': event.received_at,
                    })
        all_comments.sort(key=lambda x: x['sort_key'], reverse=True)

        _last_msgs_options = [1, 3, 5, 10]
        try:
            last_msgs_count = int(request.GET.get('last_msgs', 3))
            if last_msgs_count not in _last_msgs_options:
                last_msgs_count = 3
        except (ValueError, TypeError):
            last_msgs_count = 3
        last_messages = all_comments[:last_msgs_count]

        status_totals = [
            {'status': s, 'display': fmt(secs)}
            for s, secs in sorted(status_seconds.items())
            if secs > 0
        ]

        from settings_hub.models import get_app_setting, JiraStatusConfig
        _term_statuses = {c.status_name.lower() for c in JiraStatusConfig.objects.filter(category='done')} or {'done', 'descartado'}

        # All-time status segments for Status History card
        all_time_segments = []

        # Seed initial state from creation event
        creation_ev = next((e for e in all_events if e.event_type == 'jira:issue_created'), None)
        if creation_ev and raw_transitions:
            init_status = creation_ev.payload.get('issue', {}).get('fields', {}).get('status', {}).get('name', '')
            if init_status:
                first_exit = raw_transitions[0]['at']
                duration_secs = max(0, int((first_exit - creation_ev.received_at).total_seconds()))
                h, rem = divmod(duration_secs, 3600)
                m = rem // 60
                all_time_segments.append({
                    'status': init_status,
                    'entered_at': creation_ev.received_at.astimezone(user_tz),
                    'ongoing': False,
                    'is_terminal': init_status.lower() in _term_statuses,
                    'duration': f'{h}h {m}m' if h else f'{m}m',
                })

        for i, t in enumerate(raw_transitions):
            exited_at = raw_transitions[i + 1]['at'] if i + 1 < len(raw_transitions) else None
            is_terminal = t['to_status'].lower() in _term_statuses
            if is_terminal and exited_at is None:
                all_time_segments.append({
                    'status': t['to_status'],
                    'entered_at': t['at'].astimezone(user_tz),
                    'ongoing': False,
                    'is_terminal': True,
                    'duration': None,
                })
            else:
                duration_secs = max(0, int(((exited_at or now) - t['at']).total_seconds()))
                h, rem = divmod(duration_secs, 3600)
                m = rem // 60
                all_time_segments.append({
                    'status': t['to_status'],
                    'entered_at': t['at'].astimezone(user_tz),
                    'ongoing': exited_at is None,
                    'is_terminal': False,
                    'duration': f'{h}h {m}m' if h else f'{m}m',
                })
        jira_base_url = get_app_setting('jira_base_url', '').rstrip('/')
        jira_url = f'{jira_base_url}/browse/{ticket.issue_key}' if jira_base_url else ''

        back_range = request.GET.get('back_range', 'today')
        back_tags = request.GET.getlist('back_tags')
        back_statuses = request.GET.getlist('back_statuses')

        return render(request, 'timetracking/ticket_timeline.html', {
            'ticket': ticket,
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'comments': comments,
            'timeline': timeline,
            'status_totals': status_totals,
            'total_manual_minutes': total_manual_minutes,
            'total_manual_display': fmt(total_manual_minutes * 60),
            'back_range': back_range,
            'back_tags': back_tags,
            'back_statuses': back_statuses,
            'last_messages': last_messages,
            'last_msgs_count': last_msgs_count,
            'last_msgs_options': _last_msgs_options,
            'all_time_segments': all_time_segments,
            'jira_url': jira_url,
        })
