import os
import logging
import firebase_admin
from firebase_admin import credentials, auth
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger("betterresume.api.auth")

# Initialize Firebase Admin
# We try to initialize. If no credentials are found (env var GOOGLE_APPLICATION_CREDENTIALS),
# it might fail or work if on GCP.
try:
    if not firebase_admin._apps:
        # Check if we have explicit credentials content in env (sometimes useful for deployment without file)
        # Otherwise default strategy.
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin initialized with default credentials")
except Exception as e:
    logger.warning("Failed to initialize Firebase Admin: %s. Auth verification might fail or be bypassed in dev.", e)
    # If we want to allow dev mode without real verification:
    # firebase_admin.initialize_app(credentials.AnonymousCredentials())? No such thing easily.
    # We'll handle the verification logic to allow bypass if configured.

security = HTTPBearer()

async def get_current_user(creds: HTTPAuthorizationCredentials = Security(security)):
    """
    Verify the Firebase ID token and return the user's decoded token data.
    """
    token = creds.credentials
    
    # DEV BYPASS: If explicitly allowed or if firebase failed to init
    if os.getenv("DEV_AUTH_BYPASS") == "1":
         return {"uid": "dev-admin", "email": "admin@example.com", "admin": True}

    if not firebase_admin._apps:
        # If firebase not init and not bypassed, we can't secure it properly.
        # For this specific request, I'll allow it if logic dictates, but generally this is an error.
        logger.error("Firebase not initialized, cannot verify token.")
        raise HTTPException(status_code=500, detail="Auth configuration error")

    try:
        decoded_token = auth.verify_id_token(token)
        return decoded_token
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")

from utils.db_storage import DBStorage

async def get_current_admin(user: dict = Security(get_current_user)):
    """
    Ensure the user is an admin by checking the database `is_admin` flag.
    If database check fails, falls back to env var admin emails for safety.
    """
    user_id = user.get("uid")
    if not user_id:
         raise HTTPException(status_code=401, detail="Invalid user ID")
         
    # Ensure user record exists with email
    db = DBStorage()
    db._ensure_user(user_id, email=user.get("email"))

    if db.is_admin(user_id):
        return user

    # Fallback / Bootstrap: Check env var
    admin_emails = os.getenv("ADMIN_EMAILS", "").split(",")
    user_email = user.get("email", "")
    
    if user_email and admin_emails and user_email in admin_emails:
        # Auto-promote if in env var list
        db.set_admin(user_id, True)
        return user
        
    raise HTTPException(status_code=403, detail="Not authorized (Admin only)")
