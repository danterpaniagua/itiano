from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False


class CustomUserAdmin(UserAdmin):
    inlines = [UserProfileInline]

    def save_formset(self, request, form, formset, change):
        if formset.model is UserProfile:
            instances = formset.save(commit=False)
            for instance in instances:
                UserProfile.objects.update_or_create(
                    user=instance.user,
                    defaults={'role': instance.role},
                )
            formset.save_m2m()
        else:
            super().save_formset(request, form, formset, change)


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(UserProfile)
