# utils.py
from tickets.models import Ticket

def sanitize_text(text):
    return text.encode('utf-8', errors='ignore').decode('utf-8') if text else ""

def get_agent_active_ticket(telegram_id: int):
    return Ticket.objects.filter(
        agent__telegram_id=telegram_id,
        is_claimed=True,
        is_resolved=False,
        is_closed=False,
    ).order_by("-created_at").first()

def get_active_ticket_for_customer(customer):
    """
    Return the most recent ticket that is NOT finally approved as resolved/closed.
    If none exists, return None (the next message will create a fresh ticket).
    """
    return Ticket.objects.filter(
        customer=customer,
        is_resolved_approved=False,
        is_closed_approved=False,
    ).order_by("-created_at").first()
