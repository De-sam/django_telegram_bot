from django.db import models
from customers.models import Customer
from agents.models import Agent

class Ticket(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    agent = models.ForeignKey(Agent, on_delete=models.SET_NULL, null=True, blank=True)
    is_claimed = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)  # True when ticket is resolved
    is_resolved_approved = models.BooleanField(default=False)  # Admin approval for resolution
    is_closed = models.BooleanField(default=False)  # True when ticket is closed
    is_closed_approved = models.BooleanField(default=False)  # Admin approval for closure
    resolution_summary = models.TextField(null=True, blank=True)  # Summary provided by the agent when resolving
    closure_summary = models.TextField(null=True, blank=True)  # Summary provided by the agent when closing
    resolved_at = models.DateTimeField(null=True, blank=True)  # Timestamp of when the ticket was resolved
    closed_at = models.DateTimeField(null=True, blank=True)  # Timestamp of when the ticket was closed
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Ticket #{self.id} for Customer {self.customer.id}"
