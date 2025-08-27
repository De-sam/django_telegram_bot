
from django.conf import settings
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from tickets.models import Ticket
from agents.models import Agent
from customers.models import Customer, CustomerMessage
from admin_app.models import AdminDecision
import logging

logger = logging.getLogger(__name__)

def claim_ticket(ticket_id: int, telegram_id: int):
    try:
        agent = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.error(f"Agent not found for telegram_id {telegram_id}")
        return {"status": "error", "message": "Only registered agents can claim tickets."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found")
        return {"status": "error", "message": "Ticket not found."}
    has_active = Ticket.objects.filter(
        agent=agent,
        is_claimed=True,
        is_resolved=False,
        is_closed=False
    ).exists()
    if has_active:
        logger.warning(f"Agent {telegram_id} attempted to claim ticket {ticket_id} with active ticket")
        return {"status": "error", "message": "You already have an active ticket. Please resolve or close it before claiming another."}
    if ticket.is_claimed:
        logger.warning(f"Ticket {ticket_id} already claimed")
        return {"status": "error", "message": "Ticket already claimed."}
    with transaction.atomic():
        ticket.agent = agent
        ticket.is_claimed = True
        ticket.is_resolved = False
        ticket.is_closed = False
        ticket.is_resolved_approved = False
        ticket.is_closed_approved = False
        ticket.customer.open_ticket = True
        ticket.customer.open_ticket_spam = 0
        ticket.customer.save()
        ticket.save()
        # Mark all unforwarded messages for this ticket as forwarded
        CustomerMessage.objects.filter(ticket=ticket, is_forwarded=False).update(is_forwarded=True)
    logger.info(f"Ticket {ticket_id} claimed by agent {telegram_id}")
    return {
        "status": "success",
        "ticket": ticket,
        "agent": agent,
    }

def resolve_ticket(ticket_id: int, telegram_id: int, summary: str):
    try:
        agent = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.error(f"Agent not found for telegram_id {telegram_id}")
        return {"status": "error", "message": "Only registered agents can resolve tickets."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found")
        return {"status": "error", "message": "Ticket not found."}
    if ticket.is_resolved:
        logger.warning(f"Ticket {ticket_id} already resolved")
        return {"status": "error", "message": "This ticket is already resolved."}
    if ticket.is_closed:
        logger.warning(f"Ticket {ticket_id} is closed, cannot resolve")
        return {"status": "error", "message": "This ticket is closed and cannot be resolved."}
    with transaction.atomic():
        ticket.is_resolved = True
        ticket.resolution_summary = summary
        ticket.resolved_at = timezone.now()
        ticket.is_resolved_approved = False
        ticket.save()
    logger.info(f"Ticket {ticket_id} marked as resolved by agent {telegram_id}")
    return {"status": "success", "message": "Ticket has been marked as resolved. Waiting for admin approval."}

def close_ticket(ticket_id: int, telegram_id: int, summary: str):
    try:
        agent = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.error(f"Agent not found for telegram_id {telegram_id}")
        return {"status": "error", "message": "Only registered agents can close tickets."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found")
        return {"status": "error", "message": "Ticket not found."}
    if ticket.is_closed:
        logger.warning(f"Ticket {ticket_id} already closed")
        return {"status": "error", "message": "This ticket is already closed."}
    if ticket.is_resolved:
        logger.warning(f"Ticket {ticket_id} is resolved, cannot close")
        return {"status": "error", "message": "This ticket is resolved and cannot be closed."}
    with transaction.atomic():
        ticket.is_closed = True
        ticket.closure_summary = summary
        ticket.closed_at = timezone.now()
        ticket.is_closed_approved = False
        ticket.save()
    logger.info(f"Ticket {ticket_id} marked as closed by agent {telegram_id}")
    return {"status": "success", "message": "Ticket has been marked as closed. Waiting for admin approval."}

def approve_ticket_resolution(ticket_id: int, telegram_id: int):
    # Check if the user is an admin
    if telegram_id not in settings.ADMIN_IDS:
        logger.error(f"Unauthorized resolution approval attempt by telegram_id {telegram_id} for ticket {ticket_id}")
        return {"status": "error", "message": "Only admins can approve this action."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found for resolution approval")
        return {"status": "error", "message": "Ticket not found."}
    if not ticket.is_resolved:
        logger.warning(f"Ticket {ticket_id} not resolved, cannot approve")
        return {"status": "error", "message": "This ticket has not been resolved."}
    # Try to get admin as Agent, but allow None
    admin = None
    try:
        admin = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.warning(f"Admin with telegram_id {telegram_id} is not an Agent, proceeding with null admin")
    # Store agent Telegram ID before unlinking
    agent_telegram_id = ticket.agent.telegram_id if ticket.agent else None
    with transaction.atomic():
        ticket.is_resolved_approved = True
        ticket.is_closed = False
        ticket.is_claimed = False
        ticket.agent = None
        ticket.customer.open_ticket = True
        ticket.customer.open_ticket_spam = 0
        ticket.customer.save()
        ticket.save()
        AdminDecision.objects.create(
            ticket=ticket,
            admin=admin,  # Can be None
            decision_type='resolve',
            decision='approved'
        )
        # Mark all messages for this ticket as forwarded to reset message count
        CustomerMessage.objects.filter(ticket=ticket).update(is_forwarded=True)
    logger.info(f"Resolution approved for ticket {ticket_id} by admin {telegram_id}, agent unlinked")
    return {
        "status": "success",
        "message": "Ticket resolution has been approved and agent unlinked.",
        "agent_telegram_id": agent_telegram_id
    }

def decline_ticket_resolution(ticket_id: int, telegram_id: int):
    # Check if the user is an admin
    if telegram_id not in settings.ADMIN_IDS:
        logger.error(f"Unauthorized resolution decline attempt by telegram_id {telegram_id} for ticket {ticket_id}")
        return {"status": "error", "message": "Only admins can approve this action."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found for resolution decline")
        return {"status": "error", "message": "Ticket not found."}
    # Try to get admin as Agent, but allow None
    admin = None
    try:
        admin = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.warning(f"Admin with telegram_id {telegram_id} is not an Agent, proceeding with null admin")
    # Store agent Telegram ID for notifications
    agent_telegram_id = ticket.agent.telegram_id if ticket.agent else None
    with transaction.atomic():
        ticket.is_resolved = False
        ticket.is_resolved_approved = False
        ticket.resolution_summary = None
        ticket.resolved_at = None
        ticket.save()
        AdminDecision.objects.create(
            ticket=ticket,
            admin=admin,  # Can be None
            decision_type='resolve',
            decision='declined'
        )
    logger.info(f"Resolution declined for ticket {ticket_id} by admin {telegram_id}")
    return {
        "status": "success",
        "message": "Ticket resolution has been declined.",
        "agent_telegram_id": agent_telegram_id
    }

def approve_ticket_closure(ticket_id: int, telegram_id: int):
    # Check if the user is an admin
    if telegram_id not in settings.ADMIN_IDS:
        logger.error(f"Unauthorized closure approval attempt by telegram_id {telegram_id} for ticket {ticket_id}")
        return {"status": "error", "message": "Only admins can approve this action."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found for closure approval")
        return {"status": "error", "message": "Ticket not found."}
    if not ticket.is_closed:
        logger.warning(f"Ticket {ticket_id} not closed, cannot approve")
        return {"status": "error", "message": "This ticket has not been closed."}
    # Try to get admin as Agent, but allow None
    admin = None
    try:
        admin = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.warning(f"Admin with telegram_id {telegram_id} is not an Agent, proceeding with null admin")
    # Store agent Telegram ID before unlinking
    agent_telegram_id = ticket.agent.telegram_id if ticket.agent else None
    with transaction.atomic():
        ticket.is_closed_approved = True
        ticket.is_closed = False
        ticket.is_claimed = False
        ticket.agent = None
        ticket.customer.open_ticket = True
        ticket.customer.open_ticket_spam = 0
        ticket.customer.save()
        ticket.save()
        AdminDecision.objects.create(
            ticket=ticket,
            admin=admin,  # Can be None
            decision_type='close',
            decision='approved'
        )
        # Mark all messages for this ticket as forwarded to reset message count
        CustomerMessage.objects.filter(ticket=ticket).update(is_forwarded=True)
    logger.info(f"Closure approved for ticket {ticket_id} by admin {telegram_id}, agent unlinked")
    return {
        "status": "success",
        "message": "Ticket closure has been approved and agent unlinked.",
        "agent_telegram_id": agent_telegram_id
    }

def decline_ticket_closure(ticket_id: int, telegram_id: int):
    # Check if the user is an admin
    if telegram_id not in settings.ADMIN_IDS:
        logger.error(f"Unauthorized closure decline attempt by telegram_id {telegram_id} for ticket {ticket_id}")
        return {"status": "error", "message": "Only admins can approve this action."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found for closure decline")
        return {"status": "error", "message": "Ticket not found."}
    # Try to get admin as Agent, but allow None
    admin = None
    try:
        admin = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.warning(f"Admin with telegram_id {telegram_id} is not an Agent, proceeding with null admin")
    # Store agent Telegram ID for notifications
    agent_telegram_id = ticket.agent.telegram_id if ticket.agent else None
    with transaction.atomic():
        ticket.is_closed = False
        ticket.is_closed_approved = False
        ticket.closure_summary = None
        ticket.closed_at = None
        ticket.save()
        AdminDecision.objects.create(
            ticket=ticket,
            admin=admin,  # Can be None
            decision_type='close',
            decision='declined'
        )
    logger.info(f"Closure declined for ticket {ticket_id} by admin {telegram_id}")
    return {
        "status": "success",
        "message": "Ticket closure has been declined.",
        "agent_telegram_id": agent_telegram_id
    }

def raise_ticket(ticket_id: int):
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found for raising")
        return {"status": "error", "message": "Ticket not found."}
    if not (ticket.is_closed_approved or ticket.is_resolved_approved):
        logger.warning(f"Ticket {ticket_id} neither closed nor resolved approved, cannot raise")
        return {"status": "error", "message": "This ticket's closure or resolution has not been approved."}
    with transaction.atomic():
        ticket.is_closed = False
        ticket.is_closed_approved = False
        ticket.is_resolved = False
        ticket.is_resolved_approved = False
        ticket.is_claimed = False
        ticket.agent = None
        ticket.customer.open_ticket = True
        ticket.customer.open_ticket_spam = 0
        ticket.customer.save()
        ticket.save()
        # Mark all messages for this ticket as forwarded to reset message count
        CustomerMessage.objects.filter(ticket=ticket).update(is_forwarded=True)
    logger.info(f"Ticket {ticket_id} raised back to support group, reset open_ticket_spam for customer {ticket.customer.telegram_id}")
    return {"status": "success", "message": "Ticket raised back to support group."}

def handle_ticket(ticket_id: int, telegram_id: int):
    # Check if the user is an admin
    if telegram_id not in settings.ADMIN_IDS:
        logger.error(f"Unauthorized handle attempt by telegram_id {telegram_id} for ticket {ticket_id}")
        return {"status": "error", "message": "Only admins can handle this action."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found for handling")
        return {"status": "error", "message": "Ticket not found."}
    if not (ticket.is_closed_approved or ticket.is_resolved_approved):
        logger.warning(f"Ticket {ticket_id} neither closed nor resolved approved, cannot handle")
        return {"status": "error", "message": "This ticket's closure or resolution has not been approved."}
    # Try to get admin as Agent, but allow None for assignment
    admin = None
    try:
        admin = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.warning(f"Admin with telegram_id {telegram_id} is not an Agent, assigning ticket with null agent")
    with transaction.atomic():
        ticket.agent = admin  # Can be None
        ticket.is_claimed = True
        ticket.is_closed = False
        ticket.is_closed_approved = False
        ticket.is_resolved = False
        ticket.is_resolved_approved = False
        ticket.customer.open_ticket = True
        ticket.customer.open_ticket_spam = 0
        ticket.customer.save()
        ticket.save()
        # Mark all messages for this ticket as forwarded to reset message count
        CustomerMessage.objects.filter(ticket=ticket).update(is_forwarded=True)
    logger.info(f"Ticket {ticket_id} assigned to admin {telegram_id} for handling")
    return {"status": "success", "message": "Ticket assigned to admin for handling."}

def close_ticket_finally(ticket_id: int, telegram_id: int):
    # Check if the user is an admin
    if telegram_id not in settings.ADMIN_IDS:
        logger.error(f"Unauthorized final closure attempt by telegram_id {telegram_id} for ticket {ticket_id}")
        return {"status": "error", "message": "Only admins can approve this action."}
    try:
        ticket = Ticket.objects.get(id=ticket_id)
    except Ticket.DoesNotExist:
        logger.error(f"Ticket {ticket_id} not found for final closure")
        return {"status": "error", "message": "Ticket not found."}
    if not (ticket.is_closed_approved or ticket.is_resolved_approved):
        logger.warning(f"Ticket {ticket_id} neither closed nor resolved approved, cannot close finally")
        return {"status": "error", "message": "This ticket's closure or resolution has not been approved."}
    # Try to get admin as Agent, but allow None
    admin = None
    try:
        admin = Agent.objects.get(telegram_id=telegram_id)
    except Agent.DoesNotExist:
        logger.warning(f"Admin with telegram_id {telegram_id} is not an Agent, proceeding with null admin")
    # Store agent Telegram ID for notifications
    agent_telegram_id = ticket.agent.telegram_id if ticket.agent else None
    with transaction.atomic():
        ticket.is_closed = True
        ticket.is_closed_approved = True
        ticket.is_resolved = True
        ticket.is_resolved_approved = True
        ticket.is_claimed = False
        ticket.agent = None
        ticket.closed_at = timezone.now()
        ticket.customer.open_ticket = False
        ticket.customer.save()
        ticket.save()
        AdminDecision.objects.create(
            ticket=ticket,
            admin=admin,  # Can be None
            decision_type='close',
            decision='final'
        )
        # Mark all messages for this ticket as forwarded to reset message count
        CustomerMessage.objects.filter(ticket=ticket).update(is_forwarded=True)
    logger.info(f"Ticket {ticket_id} permanently closed by admin {telegram_id}")
    return {
        "status": "success",
        "message": "Ticket has been permanently closed.",
        "agent_telegram_id": agent_telegram_id
    }
