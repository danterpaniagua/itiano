import datetime as dt
import zoneinfo

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from contacts.models import Contact, ContactChannel
from itsm.models import Category, Tag
from timetracking.models import WorkSchedule
from .models import get_app_setting, AppSetting

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


class SettingsIndexView(StaffRequiredMixin, View):
    def get(self, request):
        return redirect('settings-tags')


class TagListView(StaffRequiredMixin, View):
    def get(self, request):
        qs = Tag.objects.annotate(
            usage=Count('ticket_tags'),
            auto_count=Count('ticket_tags', filter=Q(ticket_tags__source='automation')),
        ).order_by('name')
        manual_tags = [t for t in qs if t.auto_count == 0]
        jira_tags = [t for t in qs if t.auto_count > 0]
        return render(request, 'settings_hub/tag_list.html', {
            'manual_tags': manual_tags,
            'jira_tags': jira_tags,
            'active': 'tags',
        })


class TagCreateView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '').strip()
        if not name:
            messages.error(request, 'El nombre es obligatorio.')
            return redirect('settings-tags')
        if Tag.objects.filter(name=name).exists():
            messages.error(request, f'El tag "{name}" ya existe.')
            return redirect('settings-tags')
        tag = Tag.objects.create(name=name, color=color)
        messages.success(request, f'Tag "{tag.name}" creado.')
        return redirect('settings-tags')


def _tag_is_jira_owned(tag):
    return tag.ticket_tags.filter(source='automation').exists()


class TagEditView(StaffRequiredMixin, View):
    def get(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede editarse.')
            return redirect('settings-tags')
        return render(request, 'settings_hub/tag_form.html', {'tag': tag, 'active': 'tags'})

    def post(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede editarse.')
            return redirect('settings-tags')
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
        return redirect('settings-tags')


class TagDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        tag = get_object_or_404(Tag, pk=pk)
        if _tag_is_jira_owned(tag):
            messages.error(request, f'El tag "{tag.name}" es gestionado por Jira y no puede eliminarse.')
            return redirect('settings-tags')
        if tag.ticket_tags.exists():
            messages.error(request, f'El tag "{tag.name}" está en uso y no puede eliminarse.')
            return redirect('settings-tags')
        name = tag.name
        tag.delete()
        messages.success(request, f'Tag "{name}" eliminado.')
        return redirect('settings-tags')


class CategoryListView(StaffRequiredMixin, View):
    def get(self, request):
        categories = Category.objects.annotate(usage=Count('ticket')).order_by('name')
        return render(request, 'settings_hub/category_list.html', {
            'categories': categories,
            'active': 'categories',
        })


class CategoryCreateView(StaffRequiredMixin, View):
    def post(self, request):
        name = request.POST.get('name', '').strip()
        if not name:
            messages.error(request, 'El nombre es obligatorio.')
            return redirect('settings-categories')
        if Category.objects.filter(name=name).exists():
            messages.error(request, f'La categoría "{name}" ya existe.')
            return redirect('settings-categories')
        cat = Category.objects.create(name=name)
        messages.success(request, f'Categoría "{cat.name}" creada.')
        return redirect('settings-categories')


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
        return redirect('settings-categories')


class CategoryDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        name = category.name
        category.delete()
        messages.success(request, f'Categoría "{name}" eliminada.')
        return redirect('settings-categories')


class UserSettingsView(LoginRequiredMixin, View):
    def _get_schedule(self, user):
        schedule, _ = WorkSchedule.objects.get_or_create(user=user)
        return schedule

    def _ctx(self, request, schedule, editing_channel=None):
        active_days = {attr for attr, _ in _DAYS if getattr(schedule, attr)}
        contact = getattr(request.user, 'contact', None)
        channels = list(contact.channels.all()) if contact else []
        return {
            'schedule': schedule,
            'days': _DAYS,
            'active_days': active_days,
            'contact': contact,
            'channels': channels,
            'channel_types': ContactChannel.TYPES,
            'editing_channel': editing_channel,
        }

    def get(self, request):
        schedule = self._get_schedule(request.user)
        return render(request, 'settings_hub/user_settings.html', self._ctx(request, schedule))

    def post(self, request):
        schedule = self._get_schedule(request.user)
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
        schedule.save()
        messages.success(request, 'Schedule saved.')
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
    def get(self, request):
        return render(request, 'settings_hub/app_settings.html', {
            'jira_base_url': get_app_setting('jira_base_url'),
        })

    def post(self, request):
        url = request.POST.get('jira_base_url', '').strip().rstrip('/')
        AppSetting.objects.update_or_create(key='jira_base_url', defaults={'value': url})
        messages.success(request, 'App settings saved.')
        return redirect('settings-app')
