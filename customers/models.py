# customers/models.py

from django.db import models
from django.utils import timezone

def get_default_open_ticket_time():
    return timezone.make_aware(timezone.datetime(1000, 1, 1))

class Customer(models.Model):
    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    language_code = models.CharField(max_length=10, blank=True, null=True)
    open_ticket = models.BooleanField(default=False)
    banned = models.BooleanField(default=False)
    open_ticket_spam = models.IntegerField(default=1)
    open_ticket_link = models.CharField(max_length=255, blank=True, null=True)
    open_ticket_time = models.DateTimeField(default=get_default_open_ticket_time)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name or str(self.telegram_id)

class CustomerMessage(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='messages')
    ticket = models.ForeignKey("tickets.Ticket", on_delete=models.SET_NULL, null=True, blank=True, related_name='messages')
    message_text = models.TextField()
    message_type = models.CharField(max_length=50, default='text')
    telegram_message_id = models.BigIntegerField(blank=True, null=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    is_forwarded = models.BooleanField(default=False)
    is_resolved_message = models.BooleanField(default=False)
    is_closed_message = models.BooleanField(default=False)

    def __str__(self):
        return f"Message from {self.customer.telegram_id} at {self.sent_at}"