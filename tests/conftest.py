"""Shared fixtures. Pages need a signed-in user, so the default `client` is signed in."""

import pytest
from django.test import Client


@pytest.fixture
def anon_client():
    """A client with no session: what a visitor (or an event sender) gets."""
    return Client()


@pytest.fixture
def client(db, django_user_model):
    """pytest-django's client, signed in as a regular user (not staff, not superuser)."""
    user = django_user_model.objects.create_user(username="analyst", password="not-a-real-pw-1")
    signed_in = Client()
    signed_in.force_login(user)
    return signed_in
