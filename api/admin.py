from django.contrib import admin

from api.models import ApiToken


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """List and revoke (delete) tokens. New tokens come from `manage.py createapitoken`, which
    shows the plaintext once; the admin never sees it."""

    list_display = ["name", "prefix", "user", "created_at", "last_used_at"]
    readonly_fields = ["user", "name", "prefix", "token_hash", "created_at", "last_used_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
