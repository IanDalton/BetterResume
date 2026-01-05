import os
import json
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import stripe
from utils.db_storage import DBStorage

logger = logging.getLogger("betterresume.api.donations")
router = APIRouter()
db = DBStorage()

# Get Stripe secret key from environment
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY not set in environment")
stripe.api_key = STRIPE_SECRET_KEY

STRIPE_PUBLIC_KEY = os.getenv('STRIPE_PUBLIC_KEY')

@router.get("/stripe-config")
async def get_stripe_config():
    """Return the Stripe public key for frontend initialization"""
    return {"publicKey": STRIPE_PUBLIC_KEY}


@router.post("/create-donation-session")
async def create_donation_session(request: Request):
    """Create a Stripe checkout session for donations"""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body")
    
    amount = body.get('amount', 500)  # Default $5 USD
    currency = body.get('currency', 'USD').upper()
    reason = body.get('reason', 'support')
    user_id = body.get('user_id')
    
    # Validate amount (between $1 and $1000)
    if not isinstance(amount, (int, float)) or amount < 100 or amount > 100000:
        raise HTTPException(status_code=400, detail="Invalid amount")
    
    # Validate currency
    valid_currencies = ['USD', 'ARS', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY', 'MXN']
    if currency not in valid_currencies:
        raise HTTPException(status_code=400, detail=f"Unsupported currency: {currency}")
    
    try:
        
        # Get domain from request
        origin = request.headers.get('origin') or 'https://betterresume.dev'
        return_url = f"{origin}/donate-success"
        
        session = stripe.checkout.Session.create(
            ui_mode='embedded',
            line_items=[
                {
                    'price_data': {
                        'currency': currency.lower(),
                        'product_data': {
                            'name': 'Support BetterResume' if reason == 'support' else 'Job Success Celebration',
                            'description': 'Help keep BetterResume free and running' if reason == 'support' else 'Celebrating a new job!',
                        },
                        'unit_amount': int(amount),
                    },
                    'quantity': 1,
                }
            ],
            mode='payment',
            return_url=return_url,
            submit_type='donate',
            billing_address_collection='auto',
            metadata={
                'reason': reason,
                'user_id': user_id
            }
        )
        
        logger.info(
            "Created Stripe donation session: %s, amount=%d %s, reason=%s",
            session.id, amount, currency, reason
        )
        
        return JSONResponse(content={'clientSecret': session.client_secret})
    
    except Exception as e:
        logger.exception("Failed to create donation session: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session-status")
async def get_session_status(session_id: str):
    """Check the status of a Stripe checkout session"""
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session_id")
    
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        
        if session.status == 'complete':
            # Record donation if not already recorded (idempotent)
            user_id = session.metadata.get('user_id')
            reason = session.metadata.get('reason', 'support')
            db.record_donation(
                user_id=user_id,
                amount=session.amount_total,
                currency=session.currency,
                reason=reason,
                stripe_session_id=session.id,
                status=session.status
            )

        return JSONResponse(content={
            'status': session.status,
            'customer_email': session.customer_details.email if session.customer_details else None,
            'amount_total': session.amount_total,
            'currency': session.currency,
        })
    
    except Exception as e:
        logger.exception("Failed to retrieve session status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve session")

@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    endpoint_secret = os.getenv('STRIPE_WEBHOOK_SECRET')

    if not endpoint_secret:
        # If no webhook secret is configured, we can't verify signatures.
        # In production this should be an error, but for now we might skip or log.
        logger.warning("STRIPE_WEBHOOK_SECRET not set, skipping webhook processing")
        return JSONResponse(content={'status': 'ignored'})

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('metadata', {}).get('user_id')
        reason = session.get('metadata', {}).get('reason', 'support')
        amount = session.get('amount_total')
        currency = session.get('currency')
        session_id = session.get('id')
        
        db.record_donation(
            user_id=user_id,
            amount=amount,
            currency=currency,
            reason=reason,
            stripe_session_id=session_id,
            status='complete'
        )

    return JSONResponse(content={'status': 'success'})
