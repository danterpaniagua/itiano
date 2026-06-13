from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from itsm.models import Category, Tag


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
