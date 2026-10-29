"""Create a workspace and print its write key (idempotent by name)."""

import re

from django.core.management.base import BaseCommand, CommandError

from collection.models import Workspace
from collection.services import new_write_key

WRITE_KEY_PATTERN = re.compile(r"[A-Za-z0-9_\-]{16,64}")


class Command(BaseCommand):
    help = (
        "Create a workspace for event collection and print its write key. If the workspace "
        "already exists, print its existing key."
    )

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument(
            "--write-key",
            help="Use this key instead of a random one (16-64 characters: A-Z a-z 0-9 _ -).",
        )

    def handle(self, *args, name, write_key, **options):
        if write_key and not WRITE_KEY_PATTERN.fullmatch(write_key):
            raise CommandError("--write-key must be 16-64 characters of A-Z a-z 0-9 _ -")
        workspace = Workspace.objects.filter(name=name).first()
        if workspace:
            if write_key and write_key != workspace.write_key:
                raise CommandError(f"Workspace {name!r} exists with a different write key.")
            self.stdout.write(f"Workspace {name!r} already exists.")
        else:
            if write_key and Workspace.objects.filter(write_key=write_key).exists():
                raise CommandError("That write key belongs to another workspace.")
            workspace = Workspace.objects.create(name=name, write_key=write_key or new_write_key())
            self.stdout.write(self.style.SUCCESS(f"Created workspace {name!r}."))
        self.stdout.write(f"Write key: {workspace.write_key}")
