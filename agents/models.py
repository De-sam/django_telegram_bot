from django.db import models
from customers.models import Customer

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

class AgentMessage(models.Model):
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='messages')
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    ticket = models.ForeignKey('tickets.Ticket', on_delete=models.CASCADE)
    message_text = models.TextField()
    message_type = models.CharField(max_length=50, default='text')
    telegram_message_id = models.BigIntegerField(blank=True, null=True)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message from Agent {self.agent.telegram_id} to Customer {self.customer.telegram_id} at {self.sent_at}"