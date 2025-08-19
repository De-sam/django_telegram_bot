# admin_app/models.py

from django.db import models
from tickets.models import Ticket
from agents.models import Agent  # Assuming the admin is also an agent

class AdminDecision(models.Model):
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE)
    admin = models.ForeignKey(Agent, on_delete=models.CASCADE)  # Admin is linked to Agent
    decision_type = models.CharField(max_length=50, choices=[('resolve', 'Resolve'), ('close', 'Close')])
    decision = models.CharField(max_length=10, choices=[('approved', 'Approved'), ('declined', 'Declined')])
    decision_notes = models.TextField(null=True, blank=True)  # Admin’s additional notes
    decision_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Admin Decision for Ticket #{self.ticket.id}: {self.decision}"
