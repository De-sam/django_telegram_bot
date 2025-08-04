from django.contrib import admin
from .models import Customer, CustomerMessage

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('telegram_id', 'full_name', 'language_code', 'open_ticket', 'banned', 'created_at')
    search_fields = ('telegram_id', 'full_name')
    list_filter = ('open_ticket', 'banned', 'language_code')

@admin.register(CustomerMessage)
class CustomerMessageAdmin(admin.ModelAdmin):
    list_display = ('customer', 'message_type', 'sent_at', 'message_text')
    search_fields = ('message_text',)
    list_filter = ('message_type', 'sent_at')
