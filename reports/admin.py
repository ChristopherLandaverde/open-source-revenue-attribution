from django.contrib import admin

from reports.models import Account, Contact, ImportRun, Opportunity, Touchpoint

admin.site.register([Account, Contact, ImportRun, Opportunity, Touchpoint])
