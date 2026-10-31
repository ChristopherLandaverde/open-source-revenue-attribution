"""Create a read-only API token for a user and print it once."""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from api.models import ApiToken


class Command(BaseCommand):
    help = (
        "Create a token for the read-only JSON API (/api/v1/) and print it. The token acts as "
        "the user, can only read, and is shown once: only its hash is stored. Revoke it by "
        "deleting it in the admin (API tokens)."
    )

    def add_arguments(self, parser):
        parser.add_argument("username", help="The existing user the token reads as.")
        parser.add_argument("--name", default="api", help="What the token is for (default: api).")

    def handle(self, *args, username, name, **options):
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f"No user {username!r}. Create one with createsuperuser first.")
        if not user.is_active:
            raise CommandError(f"User {username!r} is inactive, so its token would be refused.")
        _, token = ApiToken.issue(user, name)
        self.stdout.write(self.style.SUCCESS(f"Created API token {name!r} for {username!r}."))
        self.stdout.write(f"Token: {token}")
        self.stdout.write("Copy it now; it is not shown again. Send it as:")
        self.stdout.write("  Authorization: Bearer <token>")
