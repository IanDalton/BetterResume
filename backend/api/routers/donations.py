import os
import json
import logging
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import stripe
        

logger = logging.getLogger("betterresume.api.donations")
router = APIRouter()

# Get Stripe secret key from environment
STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY not set in environment")
stripe.api_key = STRIPE_SECRET_KEY


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
                            'name': 'Support BetterResume',
                            'description': 'Help keep BetterResume free and running',
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
        )
        
        logger.info(
            "Created Stripe donation session: %s, amount=%d %s",
            session.id, amount, currency
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
        
        return JSONResponse(content={
            'status': session.status,
            'customer_email': session.customer_details.email if session.customer_details else None,
            'amount_total': session.amount_total,
            'currency': session.currency,
        })
    
    except Exception as e:
        logger.exception("Failed to retrieve session status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to retrieve session")
