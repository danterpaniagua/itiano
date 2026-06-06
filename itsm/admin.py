from django.contrib import admin

from .models import Category, Comment, Ticket, TicketEvent


class TicketEventInline(admin.TabularInline):
    model = TicketEvent
    extra = 0
    readonly_fields = ('actor', 'from_state', 'to_state', 'note', 'created_at')
    can_delete = False


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    readonly_fields = ('author', 'body', 'created_at')
    can_delete = False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('pk', 'title', 'type', 'state', 'priority', 'requester', 'assigned_to', 'created_at')
    list_filter = ('state', 'type', 'priority')
    search_fields = ('title', 'description')
    readonly_fields = ('state', 'created_at', 'updated_at')
    inlines = [TicketEventInline, CommentInline]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    pass


@admin.register(TicketEvent)
class TicketEventAdmin(admin.ModelAdmin):
    list_display = ('ticket', 'actor', 'from_state', 'to_state', 'created_at')
    readonly_fields = ('ticket', 'actor', 'from_state', 'to_state', 'note', 'created_at')
