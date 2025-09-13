# admin.py
#
from django.contrib import admin
from .models import Company, Application, Message

admin.site.register(Company)
admin.site.register(Application)
admin.site.register(Message)
