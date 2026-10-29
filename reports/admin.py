from django.contrib import admin

from reports.models import Account, Contact, Opportunity, Touchpoint

admin.site.register([Account, Contact, Opportunity, Touchpoint])
