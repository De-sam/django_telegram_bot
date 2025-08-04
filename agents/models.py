from django.db import models

class PendingAgent(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    full_name = models.CharField(max_length=255)
    language = models.CharField(max_length=10, null=True, blank=True)
    availability = models.TextField(null=True, blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PendingAgent {self.telegram_id} - {self.full_name}"


class Agent(models.Model):
    telegram_id = models.BigIntegerField(unique=True)
    full_name = models.CharField(max_length=255)
    language = models.CharField(max_length=10, null=True, blank=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Agent {self.telegram_id} - {self.full_name}"
