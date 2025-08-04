# customers/models.py

from django.db import models
from django.utils import timezone

class Customer(models.Model):
    telegram_id = models.BigIntegerField(unique=True, db_index=True)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    language_code = models.CharField(max_length=10, blank=True, null=True)  # e.g., 'en', 'es', 'ru'

    open_ticket = models.BooleanField(default=False)
    banned = models.BooleanField(default=False)
    open_ticket_spam = models.IntegerField(default=1)
    open_ticket_link = models.CharField(max_length=255, blank=True, null=True)
    open_ticket_time = models.DateTimeField(default=timezone.datetime(1000, 1, 1))

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name or str(self.telegram_id)



# customers/models.py (continued)

class CustomerMessage(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='messages')
    message_text = models.TextField()
    message_type = models.CharField(max_length=50, default='text')  # optional: 'text', 'photo', 'voice', etc.
    telegram_message_id = models.BigIntegerField(blank=True, null=True)  # optional tracking
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message from {self.customer.telegram_id} at {self.sent_at}"
