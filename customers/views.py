from .models import Customer

def get_or_create_customer(user):
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    customer, _ = Customer.objects.get_or_create(
        telegram_id=user.id,
        defaults={
            'full_name': full_name,
            'language_code': user.language_code
        }
    )

    # Optionally update name or language
    if customer.full_name != full_name or customer.language_code != user.language_code:
        customer.full_name = full_name
        customer.language_code = user.language_code
        customer.save()

    return customer
