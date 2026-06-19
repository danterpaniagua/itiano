import datetime as dt
import zoneinfo

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from contacts.models import Contact, ContactChannel
from core.models import UserProfile
from itsm.models import Category, Tag
from jira_integration.models import JiraEvent
from timetracking.models import WorkSchedule
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


class SettingsIndexView(LoginRequiredMixin, View):
    def get(self, request):
        return redirect('settings-user')


class TagListView(StaffRequiredMixin, View):
    def get(self, request):
        return redirect('settings-app')


class TagCreateView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '').strip()
        if not name:
            messages.error(request, 'El nombre es obligatorio.')
            return redirect('settings-app')
        if Tag.objects.filter(name=name).exists():
            messages.error(request, f'El tag "{name}" ya existe.')
            return redirect('settings-app')
        tag = Tag.objects.create(name=name, color=color)
        messages.success(request, f'Tag "{tag.name}" creado.')
        return redirect('settings-app')


def _tag_is_jira_owned(tag):
    return tag.ticket_tags.filter(source='automation').exists()


class TagEditView(StaffRequiredMixin, View):
    def get(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede editarse.')
            return redirect('settings-app')
        return render(request, 'settings_hub/tag_form.html', {'tag': tag, 'active': 'tags'})

    def post(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede editarse.')
            return redirect('settings-app')
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
        return redirect('settings-app')


class TagDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede eliminarse.')
            return redirect('settings-app')
        if tag.ticket_tags.exists():
            messages.error(request, f'El tag "{tag.name}" está en uso y no puede eliminarse.')
            return redirect('settings-app')
        name = tag.name
        tag.delete()
        messages.success(request, f'Tag "{name}" eliminado.')
        return redirect('settings-app')


class CategoryListView(StaffRequiredMixin, View):
    def get(self, request):
        return redirect('settings-app')


class CategoryCreateView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'El nombre es obligatorio.')
            return redirect('settings-app')
        if Category.objects.filter(name=name).exists():
            messages.error(request, f'La categoría "{name}" ya existe.')
            return redirect('settings-app')
        cat = Category.objects.create(name=name)
        messages.success(request, f'Categoría "{cat.name}" creada.')
        return redirect('settings-app')


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
        return redirect('settings-app')


class CategoryDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        name = category.name
        category.delete()
        messages.success(request, f'Categoría "{name}" eliminada.')
        return redirect('settings-app')


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
            'jira_accounts': _jira_accounts(),
        }

    def get(self, request):
        schedule = self._get_schedule(request.user)
        return render(request, 'settings_hub/user_settings.html', self._ctx(request, schedule))

    def post(self, request):
        schedule = self._get_schedule(request.user)
        profile = self._get_profile(request.user)

        jira_account_id = request.POST.get('jira_account_id', '').strip()
        profile.jira_account_id = jira_account_id
        profile.save(update_fields=['jira_account_id'])

        for attr, _ in _DAYS:
            setattr(schedule, attr, attr in request.POST)
        schedule.jira_username = request.POST.get('jira_username', '').strip()
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
        user = request.user
        user.first_name = request.POST.get('first_name', '').strip()
        user.last_name = request.POST.get('last_name', '').strip()
        user.save(update_fields=['first_name', 'last_name'])
        schedule.save()
        messages.success(request, 'Settings saved.')
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


class AppSettingsView(StaffRequiredMixin, View):
    def _ctx(self):
        qs = Tag.objects.annotate(
            usage=Count('ticket_tags'),
            auto_count=Count('ticket_tags', filter=Q(ticket_tags__source='automation')),
        ).order_by('name')
        return {
            'jira_base_url': get_app_setting('jira_base_url'),
            'jira_statuses': JiraStatusConfig.objects.all(),
            'category_choices': JiraStatusConfig.CATEGORY_CHOICES,
            'manual_tags': [t for t in qs if t.auto_count == 0],
            'jira_tags': [t for t in qs if t.auto_count > 0],
            'categories': Category.objects.annotate(usage=Count('ticket')).order_by('name'),
        }

    def get(self, request):
        return render(request, 'settings_hub/app_settings.html', self._ctx())

    def post(self, request):
        url = request.POST.get('jira_base_url', '').strip().rstrip('/')
        AppSetting.objects.update_or_create(key='jira_base_url', defaults={'value': url})
        messages.success(request, 'Settings saved.')
        return redirect('settings-app')


class JiraStatusAddView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('status_name', '').strip()
        category = request.POST.get('category', 'other').strip()
        valid_cats = {c for c, _ in JiraStatusConfig.CATEGORY_CHOICES}
        if not name:
            messages.error(request, 'Status name is required.')
        elif category not in valid_cats:
            messages.error(request, 'Invalid category.')
        elif JiraStatusConfig.objects.filter(status_name__iexact=name).exists():
            messages.error(request, f'"{name}" is already configured.')
        else:
            JiraStatusConfig.objects.create(status_name=name, category=category)
            messages.success(request, f'"{name}" added.')
        return redirect('settings-app')


class JiraStatusDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        JiraStatusConfig.objects.filter(pk=pk).delete()
        return redirect('settings-app')
