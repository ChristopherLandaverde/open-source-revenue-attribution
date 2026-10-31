"""Per-user API tokens for the read-only JSON API (/api/v1/).

A token is shown once, when `manage.py createapitoken` makes it. Only its SHA-256 hash is
stored, as PostHog does for personal API keys; tokens are 256-bit random values, so a plain
hash is enough (no slow password hash needed). Deleting the row revokes the token.
"""

import hashlib
import secrets

from django.conf import settings
from django.db import models

TOKEN_PREFIX = "osra_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class ApiToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_tokens"
    )
    name = models.CharField(max_length=100, help_text="What the token is for, e.g. 'my agent'.")
    prefix = models.CharField(max_length=16, help_text="The token's first characters, to find it.")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "API token"

    def __str__(self):
        return f"{self.name} ({self.prefix}…, {self.user})"

    @classmethod
    def issue(cls, user, name: str) -> tuple["ApiToken", str]:
        """Create a token for `user`; returns the record and the plaintext (shown only once)."""
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = cls.objects.create(
            user=user, name=name, prefix=token[:12], token_hash=hash_token(token)
        )
        return record, token
