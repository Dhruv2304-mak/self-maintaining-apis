"""Payment helpers for the checkout flow.

This module is deliberately OUT OF DATE. Both functions below still call
Stripe's old Charges API, which Stripe has since removed, so this is the kind
of file the scanner is meant to find and the fixer is meant to update.
"""

import stripe

# All amounts in this module are in the smallest currency unit (cents),
# because that is what the Stripe API expects.
DEFAULT_CURRENCY = "usd"


def charge_customer(amount, token):
    """Charge a customer once, using a card token from the checkout form.

    Args:
        amount: Amount to charge, in cents.
        token: A one-time card token created by Stripe.js in the browser.

    Returns:
        The Charge object Stripe sends back.
    """
    return stripe.Charge.create(
        amount=amount,
        currency=DEFAULT_CURRENCY,
        source=token,  # card token from the front end
    )


def charge_with_receipt(amount, token, email):
    """Charge a customer and ask Stripe to email them a receipt."""
    # `description` is what the customer sees on their bank statement.
    return stripe.Charge.create(
        amount=amount,
        currency=DEFAULT_CURRENCY,
        source=token,
        description="Order payment",
        receipt_email=email,
    )
