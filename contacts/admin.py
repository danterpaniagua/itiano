from django.contrib import admin
from .models import Contact, ContactChannel


class ContactChannelInline(admin.TabularInline):
    model = ContactChannel
    extra = 0


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'user', 'created_at']
    search_fields = ['first_name', 'last_name', 'user__username']
    inlines = [ContactChannelInline]
