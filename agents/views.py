# agents/views.py

from .models import Agent, PendingAgent

def create_pending_agent(user_id, full_name, language=None, availability=None):
    return PendingAgent.objects.create(
        telegram_id=user_id,
        full_name=full_name,
        language=language,
        availability=availability
    )

def get_pending_agent(user_id):
    try:
        return PendingAgent.objects.get(telegram_id=user_id)
    except PendingAgent.DoesNotExist:
        return None

def approve_pending_agent(user_id):
    pending = get_pending_agent(user_id)
    if not pending:
        return None

    agent = Agent.objects.create(
        telegram_id=pending.telegram_id,
        full_name=pending.full_name,
        language=pending.language,
    )
    pending.delete()
    return agent

def is_registered_agent(user_id):
    return Agent.objects.filter(telegram_id=user_id).exists()
