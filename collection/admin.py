from django.contrib import admin

from collection.models import CollectedEvent, Workspace

admin.site.register([CollectedEvent, Workspace])
