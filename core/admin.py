from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class CustomUserAdmin(UserAdmin):
    inlines = [UserProfileInline]
    list_display = ('avatar_thumb', 'username', 'email', 'first_name', 'last_name', 'is_staff', 'last_login')
    readonly_fields = UserAdmin.readonly_fields + ('last_login',)

    @admin.display(description='')
    def avatar_thumb(self, obj):
        try:
            url = obj.userprofile.avatar_url()
        except UserProfile.DoesNotExist:
            return ''
        return format_html(
            '<img src="{}" width="32" height="32" style="border-radius:50%;object-fit:cover">',
            url,
        )

    def save_formset(self, request, form, formset, change):
        if formset.model is UserProfile:
            instances = formset.save(commit=False)
            for instance in instances:
                UserProfile.objects.update_or_create(
                    user=instance.user,
                    defaults={'role': instance.role, 'avatar': instance.avatar},
                )
            formset.save_m2m()
        else:
            super().save_formset(request, form, formset, change)


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(UserProfile)
