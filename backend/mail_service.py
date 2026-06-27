import os
import logging
from services.email_service import send_email

# Keep the export so other files importing it don't break
__all__ = ["send_email"]

