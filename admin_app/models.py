# admin_app/models.py

from django.db import models
from tickets.models import Ticket
from agents.models import Agent  # Assuming the admin is also an agent

class AdminDecision(models.Model):
    DECISION_TYPE_CHOICES = [
        ('resolve', 'Resolve'),
        ('close', 'Close'),
    ]
    DECISION_CHOICES = [
        ('approved', 'Approved'),
        ('declined', 'Declined'),
        ('final', 'Final'),  # <-- add this
    ]

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    admin = models.ForeignKey(Agent, on_delete=models.CASCADE, null=True, blank=True)
    decision_type = models.CharField(max_length=50, choices=DECISION_TYPE_CHOICES)
    decision = models.CharField(max_length=10, choices=DECISION_CHOICES)
    decision_notes = models.TextField(null=True, blank=True)
    decision_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Admin Decision for Ticket #{self.ticket.id}: {self.decision}"
