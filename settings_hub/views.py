import datetime as dt
import zoneinfo

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from django.contrib.auth.models import User
from django.db.models import ProtectedError

from contacts.models import Contact, ContactChannel
from core.models import Team, UserProfile
from itsm.models import Category, Tag
from jira_integration.models import JiraEvent
from timetracking.models import ReportEnvironment, ReportProject, ReportService, WorkSchedule
from vault.models import Container, ContainerAccess
from .models import get_app_setting, AppSetting, JiraStatusConfig

_DAYS = [
    ('mon', 'Monday'),
    ('tue', 'Tuesday'),
    ('wed', 'Wednesday'),
    ('thu', 'Thursday'),
    ('fri', 'Friday'),
    ('sat', 'Saturday'),
    ('sun', 'Sunday'),
]


class StaffRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_staff:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class TagListView(StaffRequiredMixin, View):
    def get(self, request):
        return redirect('settings-tickets')


class TagCreateView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '').strip()
        if not name:
            messages.error(request, 'El nombre es obligatorio.')
            return redirect('settings-tickets')
        if Tag.objects.filter(name=name).exists():
            messages.error(request, f'El tag "{name}" ya existe.')
            return redirect('settings-tickets')
        tag = Tag.objects.create(name=name, color=color)
        messages.success(request, f'Tag "{tag.name}" creado.')
        return redirect('settings-tickets')


def _tag_is_jira_owned(tag):
    return tag.ticket_tags.filter(source='automation').exists()


class TagEditView(StaffRequiredMixin, View):
    def get(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede editarse.')
            return redirect('settings-tickets')
        return render(request, 'settings_hub/tag_form.html', {'tag': tag, 'active': 'tags'})

    def post(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede editarse.')
            return redirect('settings-tickets')
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '').strip()
        if not name:
            messages.error(request, 'El nombre es obligatorio.')
            return render(request, 'settings_hub/tag_form.html', {'tag': tag, 'active': 'tags'})
        if Tag.objects.filter(name=name).exclude(pk=pk).exists():
            messages.error(request, f'El tag "{name}" ya existe.')
            return render(request, 'settings_hub/tag_form.html', {'tag': tag, 'active': 'tags'})
        tag.name = name
        tag.color = color
        tag.save()
        messages.success(request, f'Tag "{tag.name}" actualizado.')
        return redirect('settings-tickets')


class TagDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede eliminarse.')
            return redirect('settings-tickets')
        if tag.ticket_tags.exists():
            messages.error(request, f'El tag "{tag.name}" está en uso y no puede eliminarse.')
            return redirect('settings-tickets')
        name = tag.name
        tag.delete()
        messages.success(request, f'Tag "{name}" eliminado.')
        return redirect('settings-tickets')


class CategoryListView(StaffRequiredMixin, View):
    def get(self, request):
        return redirect('settings-tickets')


class CategoryCreateView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'El nombre es obligatorio.')
            return redirect('settings-tickets')
        if Category.objects.filter(name=name).exists():
            messages.error(request, f'La categoría "{name}" ya existe.')
            return redirect('settings-tickets')
        cat = Category.objects.create(name=name)
        messages.success(request, f'Categoría "{cat.name}" creada.')
        return redirect('settings-tickets')


class CategoryEditView(StaffRequiredMixin, View):
    def get(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        return render(request, 'settings_hub/category_form.html', {
            'category': category,
            'active': 'categories',
        })

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'El nombre es obligatorio.')
            return render(request, 'settings_hub/category_form.html', {
                'category': category, 'active': 'categories'
            })
        if Category.objects.filter(name=name).exclude(pk=pk).exists():
            messages.error(request, f'La categoría "{name}" ya existe.')
            return render(request, 'settings_hub/category_form.html', {
                'category': category, 'active': 'categories'
            })
        category.name = name
        category.save()
        messages.success(request, f'Categoría "{category.name}" actualizada.')
        return redirect('settings-tickets')


class CategoryDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        name = category.name
        category.delete()
        messages.success(request, f'Categoría "{name}" eliminada.')
        return redirect('settings-tickets')


class VaultSettingsView(StaffRequiredMixin, View):
    def get(self, request):
        teams = Team.objects.prefetch_related('members').all()
        containers = Container.objects.select_related('parent').prefetch_related('access_grants__team').all()
        return render(request, 'settings_hub/vault_settings.html', {
            'teams': teams,
            'containers': containers,
            'all_users': User.objects.order_by('username'),
            'all_teams': teams,
            'active': 'app',
        })


class TeamCreateView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return redirect('settings-vault')
        if Team.objects.filter(name=name).exists():
            messages.error(request, f'Team "{name}" already exists.')
            return redirect('settings-vault')
        team = Team.objects.create(name=name, description=description)
        messages.success(request, f'Team "{team.name}" created.')
        return redirect('settings-vault')


class TeamEditView(StaffRequiredMixin, View):
    def get(self, request, pk):
        team = get_object_or_404(Team, pk=pk)
        return render(request, 'settings_hub/vault_team_form.html', {'team': team, 'active': 'app'})

    def post(self, request, pk):
        team = get_object_or_404(Team, pk=pk)
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip()
        description = request.POST.get('description', '').strip()
        if not name:
            messages.error(request, 'Name is required.')
            return render(request, 'settings_hub/vault_team_form.html', {'team': team, 'active': 'app'})
        if Team.objects.filter(name=name).exclude(pk=pk).exists():
            messages.error(request, f'Team "{name}" already exists.')
            return render(request, 'settings_hub/vault_team_form.html', {'team': team, 'active': 'app'})
        if code and Team.objects.filter(code=code).exclude(pk=pk).exists():
            messages.error(request, f'Team code "{code}" is already in use.')
            return render(request, 'settings_hub/vault_team_form.html', {'team': team, 'active': 'app'})
        team.name = name
        team.code = code
        team.description = description
        team.save()
        messages.success(request, f'Team "{team.name}" updated.')
        return redirect('settings-vault')


class TeamMemberAddView(StaffRequiredMixin, View):
    def post(self, request, pk):
        team = get_object_or_404(Team, pk=pk)
        user_id = request.POST.get('user_id')
        user = User.objects.filter(pk=user_id).first()
        if not user:
            messages.error(request, 'Select a user to add.')
            return redirect('settings-vault')
        team.members.add(user)
        messages.success(request, f'{user.username} added to {team.name}.')
        return redirect('settings-vault')


class TeamMemberRemoveView(StaffRequiredMixin, View):
    def post(self, request, pk, user_pk):
        team = get_object_or_404(Team, pk=pk)
        user = get_object_or_404(User, pk=user_pk)
        team.members.remove(user)
        messages.success(request, f'{user.username} removed from {team.name}.')
        return redirect('settings-vault')


def _container_is_descendant(container, candidate_ancestor):
    """True if candidate_ancestor is container itself or anywhere in
    container's ancestor chain — used to block a parent assignment that
    would create a cycle in the container tree.
    """
    node = candidate_ancestor
    while node is not None:
        if node.pk == container.pk:
            return True
        node = node.parent
    return False


class ContainerCreateView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        parent_id = request.POST.get('parent_id')
        if not name:
            messages.error(request, 'Name is required.')
            return redirect('settings-vault')
        parent = Container.objects.filter(pk=parent_id).first() if parent_id else None
        container = Container.objects.create(name=name, parent=parent, created_by=request.user)
        messages.success(request, f'Container "{container.name}" created.')
        return redirect('settings-vault')


class ContainerEditView(StaffRequiredMixin, View):
    def get(self, request, pk):
        container = get_object_or_404(Container, pk=pk)
        other_containers = Container.objects.exclude(pk=pk)
        return render(request, 'settings_hub/vault_container_form.html', {
            'container': container, 'other_containers': other_containers, 'active': 'app',
        })

    def post(self, request, pk):
        container = get_object_or_404(Container, pk=pk)
        other_containers = Container.objects.exclude(pk=pk)
        name = request.POST.get('name', '').strip()
        parent_id = request.POST.get('parent_id')
        if not name:
            messages.error(request, 'Name is required.')
            return render(request, 'settings_hub/vault_container_form.html', {
                'container': container, 'other_containers': other_containers, 'active': 'app',
            })
        parent = Container.objects.filter(pk=parent_id).first() if parent_id else None
        if parent and _container_is_descendant(container, parent):
            messages.error(request, f'Cannot set "{parent.name}" as parent — it would create a cycle.')
            return render(request, 'settings_hub/vault_container_form.html', {
                'container': container, 'other_containers': other_containers, 'active': 'app',
            })
        container.name = name
        container.parent = parent
        container.save()
        messages.success(request, f'Container "{container.name}" updated.')
        return redirect('settings-vault')


class ContainerDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        container = get_object_or_404(Container, pk=pk)
        name = container.name
        try:
            container.delete()
            messages.success(request, f'Container "{name}" deleted.')
        except ProtectedError:
            count = container.credentials.count()
            messages.error(request, f'Cannot delete "{name}": still holds {count} credential(s).')
        return redirect('settings-vault')


class ContainerAccessAddView(StaffRequiredMixin, View):
    def post(self, request, pk):
        container = get_object_or_404(Container, pk=pk)
        team = get_object_or_404(Team, pk=request.POST.get('team_id'))
        access_level = request.POST.get('access_level', ContainerAccess.ACCESS_READ)
        _, created = ContainerAccess.objects.get_or_create(
            container=container, team=team, defaults={'access_level': access_level},
        )
        if created:
            messages.success(request, f'{team.name} granted {access_level.replace("_", "/")} access to "{container.name}".')
        else:
            messages.error(request, f'{team.name} already has access to "{container.name}".')
        return redirect('settings-vault')


class ContainerAccessLevelEditView(StaffRequiredMixin, View):
    def post(self, request, pk, access_pk):
        access = get_object_or_404(ContainerAccess, pk=access_pk, container_id=pk)
        access_level = request.POST.get('access_level')
        if access_level not in dict(ContainerAccess.ACCESS_LEVELS):
            messages.error(request, 'Invalid access level.')
            return redirect('settings-vault')
        access.access_level = access_level
        access.save()
        messages.success(request, f'{access.team.name} is now {access_level.replace("_", "/")} on "{access.container.name}".')
        return redirect('settings-vault')


class ContainerAccessRemoveView(StaffRequiredMixin, View):
    def post(self, request, pk, access_pk):
        access = get_object_or_404(ContainerAccess, pk=access_pk, container_id=pk)
        team_name, container_name = access.team.name, access.container.name
        access.delete()
        messages.success(request, f'Removed {team_name}\'s access to "{container_name}".')
        return redirect('settings-vault')


def _jira_accounts():
    seen = {}
    for event in JiraEvent.objects.order_by('-received_at').iterator(chunk_size=500):
        assignee = (event.payload or {}).get('issue', {}).get('fields', {}).get('assignee') or {}
        aid = assignee.get('accountId', '')
        name = assignee.get('displayName', '')
        if aid and aid not in seen:
            seen[aid] = name
    return [{'accountId': k, 'displayName': v} for k, v in seen.items()]


class UserSettingsView(LoginRequiredMixin, View):
    def _get_schedule(self, user):
        schedule, _ = WorkSchedule.objects.get_or_create(user=user)
        return schedule

    def _get_profile(self, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile

    def _ctx(self, request, schedule, editing_channel=None):
        active_days = {attr for attr, _ in _DAYS if getattr(schedule, attr)}
        contact = getattr(request.user, 'contact', None)
        channels = list(contact.channels.all()) if contact else []
        profile = self._get_profile(request.user)
        return {
            'schedule': schedule,
            'days': _DAYS,
            'active_days': active_days,
            'contact': contact,
            'channels': channels,
            'channel_types': ContactChannel.TYPES,
            'editing_channel': editing_channel,
            'user_obj': request.user,
            'profile': profile,
            'avatar_url': profile.avatar_url(),
            'jira_accounts': _jira_accounts(),
        }

    def get(self, request):
        schedule = self._get_schedule(request.user)
        return render(request, 'settings_hub/user_settings.html', self._ctx(request, schedule))

    def post(self, request):
        schedule = self._get_schedule(request.user)
        profile = self._get_profile(request.user)

        if 'remove_avatar' in request.POST:
            if profile.avatar:
                profile.avatar.delete(save=True)
            messages.success(request, 'Avatar removed.')
            return redirect('settings-user')

        if 'avatar' in request.FILES:
            if profile.avatar:
                profile.avatar.delete(save=False)
            profile.avatar = request.FILES['avatar']
            profile.save(update_fields=['avatar'])
            messages.success(request, 'Avatar updated.')
            return redirect('settings-user')

        section = request.POST.get('section', '')

        if section == 'profile':
            user = request.user
            user.first_name = request.POST.get('first_name', '').strip()
            user.last_name = request.POST.get('last_name', '').strip()
            user.save(update_fields=['first_name', 'last_name'])
            messages.success(request, 'Profile saved.')
            return redirect('settings-user')

        if section == 'schedule':
            for attr, _ in _DAYS:
                setattr(schedule, attr, attr in request.POST)
            tz = request.POST.get('timezone', 'UTC').strip() or 'UTC'
            try:
                zoneinfo.ZoneInfo(tz)
                schedule.timezone = tz
            except (zoneinfo.ZoneInfoNotFoundError, KeyError):
                messages.error(request, f'Invalid timezone: {tz}')
                return render(request, 'settings_hub/user_settings.html', self._ctx(request, schedule))
            start = request.POST.get('start_time', '').strip()
            end = request.POST.get('end_time', '').strip()
            try:
                schedule.start_time = dt.time.fromisoformat(start)
            except ValueError:
                messages.error(request, 'Start time is invalid.')
                return render(request, 'settings_hub/user_settings.html', self._ctx(request, schedule))
            try:
                schedule.end_time = dt.time.fromisoformat(end)
            except ValueError:
                messages.error(request, 'End time is invalid.')
                return render(request, 'settings_hub/user_settings.html', self._ctx(request, schedule))
            if schedule.start_time >= schedule.end_time:
                messages.error(request, 'End time must be after start time.')
                return render(request, 'settings_hub/user_settings.html', self._ctx(request, schedule))
            schedule.save()
            messages.success(request, 'Schedule saved.')
            return redirect('settings-user')

        if section == 'jira':
            profile.jira_account_id = request.POST.get('jira_account_id', '').strip()
            profile.save(update_fields=['jira_account_id'])
            messages.success(request, 'Jira account saved.')
            return redirect('settings-user')

        messages.error(request, 'Invalid request.')
        return redirect('settings-user')


class UserChannelCreateView(LoginRequiredMixin, View):
    def post(self, request):
        contact = getattr(request.user, 'contact', None)
        if not contact:
            contact = Contact.objects.create(
                user=request.user,
                first_name=request.user.first_name or request.user.username,
                last_name=request.user.last_name or '',
            )
        ch_type = request.POST.get('type', '').strip()
        label = request.POST.get('label', '').strip()
        value = request.POST.get('value', '').strip()
        valid_types = {t for t, _ in ContactChannel.TYPES}
        if ch_type not in valid_types:
            messages.error(request, 'Invalid channel type.')
            return redirect('settings-user')
        ContactChannel.objects.create(contact=contact, type=ch_type, label=label, value=value)
        messages.success(request, 'Channel added.')
        return redirect('settings-user')


class UserChannelEditView(LoginRequiredMixin, View):
    def _get_channel(self, request, pk):
        contact = getattr(request.user, 'contact', None)
        if not contact:
            raise PermissionDenied
        return get_object_or_404(ContactChannel, pk=pk, contact=contact)

    def get(self, request, pk):
        channel = self._get_channel(request, pk)
        return render(request, 'settings_hub/user_channel_form.html', {
            'channel': channel,
            'channel_types': ContactChannel.TYPES,
        })

    def post(self, request, pk):
        channel = self._get_channel(request, pk)
        ch_type = request.POST.get('type', '').strip()
        label = request.POST.get('label', '').strip()
        value = request.POST.get('value', '').strip()
        valid_types = {t for t, _ in ContactChannel.TYPES}
        if ch_type not in valid_types:
            messages.error(request, 'Invalid channel type.')
            return redirect('settings-user')
        channel.type = ch_type
        channel.label = label
        channel.value = value
        channel.save(update_fields=['type', 'label', 'value'])
        messages.success(request, 'Channel updated.')
        return redirect('settings-user')


class UserChannelDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        contact = getattr(request.user, 'contact', None)
        if not contact:
            raise PermissionDenied
        channel = get_object_or_404(ContactChannel, pk=pk, contact=contact)
        channel.delete()
        messages.success(request, 'Channel removed.')
        return redirect('settings-user')


class AppSettingsHubView(StaffRequiredMixin, View):
    def get(self, request):
        return render(request, 'settings_hub/app_hub.html')


class TimeReportSettingsView(StaffRequiredMixin, View):
    def _ctx(self):
        all_tags = list(Tag.objects.order_by('name'))
        projects = list(ReportProject.objects.prefetch_related('services__environments').all())
        existing_proj_names = {p.tag_name for p in projects}
        for proj in projects:
            svc_names = {s.tag_name for s in proj.services.all()}
            proj.available_svc_tags = [t for t in all_tags if t.name not in svc_names]
            for svc in proj.services.all():
                env_names = {e.tag_name for e in svc.environments.all()}
                svc.available_env_tags = [t for t in all_tags if t.name not in env_names]
        return {
            'projects': projects,
            'project_available_tags': [t for t in all_tags if t.name not in existing_proj_names],
            'stuck_threshold_hours': get_app_setting('stuck_threshold_hours', '16'),
            'trend_min_baseline_seconds': get_app_setting('trend_min_baseline_seconds', '300'),
        }

    def get(self, request):
        return render(request, 'settings_hub/time_report_settings.html', self._ctx())

    def post(self, request):
        action = request.POST.get('action')

        if action == 'set_stuck_threshold':
            value = request.POST.get('stuck_threshold_hours', '').strip()
            try:
                hours = float(value)
                if hours <= 0:
                    raise ValueError
            except ValueError:
                messages.error(request, 'Stuck threshold must be a positive number of hours.')
            else:
                AppSetting.objects.update_or_create(
                    key='stuck_threshold_hours', defaults={'value': str(hours)}
                )
                messages.success(request, 'Stuck threshold saved.')

        elif action == 'set_trend_min_baseline':
            value = request.POST.get('trend_min_baseline_seconds', '').strip()
            try:
                seconds = int(value)
                if seconds < 0:
                    raise ValueError
            except ValueError:
                messages.error(request, 'Trend minimum baseline must be a non-negative number of seconds.')
            else:
                AppSetting.objects.update_or_create(
                    key='trend_min_baseline_seconds', defaults={'value': str(seconds)}
                )
                messages.success(request, 'Trend minimum baseline saved.')

        elif action == 'add_project':
            for name in request.POST.getlist('tag_name'):
                name = name.strip()
                if name:
                    ReportProject.objects.get_or_create(tag_name=name)

        elif action == 'remove_project':
            ReportProject.objects.filter(pk=request.POST.get('project_id')).delete()

        elif action == 'add_service':
            try:
                proj = ReportProject.objects.get(pk=request.POST.get('project_id'))
                for name in request.POST.getlist('tag_name'):
                    name = name.strip()
                    if name:
                        ReportService.objects.get_or_create(project=proj, tag_name=name)
            except ReportProject.DoesNotExist:
                pass

        elif action == 'remove_service':
            ReportService.objects.filter(pk=request.POST.get('service_id')).delete()

        elif action == 'add_env':
            try:
                svc = ReportService.objects.get(pk=request.POST.get('service_id'))
                for name in request.POST.getlist('tag_name'):
                    name = name.strip()
                    if name:
                        ReportEnvironment.objects.get_or_create(service=svc, tag_name=name)
            except ReportService.DoesNotExist:
                pass

        elif action == 'remove_env':
            ReportEnvironment.objects.filter(pk=request.POST.get('env_id')).delete()

        return redirect('settings-time-report')


class JiraSettingsView(StaffRequiredMixin, View):
    def _ctx(self):
        return {
            'jira_base_url': get_app_setting('jira_base_url'),
            'jira_statuses': JiraStatusConfig.objects.all(),
            'category_choices': JiraStatusConfig.CATEGORY_CHOICES,
        }

    def get(self, request):
        return render(request, 'settings_hub/jira_settings.html', self._ctx())

    def post(self, request):
        url = request.POST.get('jira_base_url', '').strip().rstrip('/')
        AppSetting.objects.update_or_create(key='jira_base_url', defaults={'value': url})
        messages.success(request, 'Base URL saved.')
        return redirect('settings-jira')


class TicketsSettingsView(StaffRequiredMixin, View):
    def _ctx(self):
        qs = Tag.objects.annotate(
            usage=Count('ticket_tags'),
            auto_count=Count('ticket_tags', filter=Q(ticket_tags__source='automation')),
        ).order_by('name')
        return {
            'manual_tags': [t for t in qs if t.auto_count == 0],
            'jira_tags': [t for t in qs if t.auto_count > 0],
            'categories': Category.objects.annotate(usage=Count('ticket')).order_by('name'),
        }

    def get(self, request):
        return render(request, 'settings_hub/tickets_settings.html', self._ctx())


class JiraStatusAddView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('status_name', '').strip()
        category = request.POST.get('category', 'other').strip()
        is_terminal = request.POST.get('is_terminal') == 'on'
        valid_cats = {c for c, _ in JiraStatusConfig.CATEGORY_CHOICES}
        if not name:
            messages.error(request, 'Status name is required.')
        elif category not in valid_cats:
            messages.error(request, 'Invalid category.')
        elif JiraStatusConfig.objects.filter(status_name__iexact=name).exists():
            messages.error(request, f'"{name}" is already configured.')
        else:
            JiraStatusConfig.objects.create(status_name=name, category=category, is_terminal=is_terminal)
            messages.success(request, f'"{name}" added.')
        return redirect('settings-jira')


class JiraStatusDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        JiraStatusConfig.objects.filter(pk=pk).delete()
        return redirect('settings-jira')


class JiraStatusToggleTerminalView(StaffRequiredMixin, View):
    def post(self, request, pk):
        status = JiraStatusConfig.objects.filter(pk=pk).first()
        if status:
            status.is_terminal = not status.is_terminal
            status.save(update_fields=['is_terminal'])
        return redirect('settings-jira')
