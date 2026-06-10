import os
import logging
from typing import Any, Dict, List, Optional
import groq
from langchain_groq import ChatGroq
from config import API_KEY_1, API_KEY_2, API_KEY

# Configure standard logger to output clearly to stdout/console
logger = logging.getLogger("llm_failover")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[LLM-Failover] %(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

def should_failover(exc: Exception) -> bool:
    """
    Checks whether the exception qualifies for failover.
    Triggers on:
    - Rate limit errors (429)
    - Token/request size rate limit errors (413 with rate_limit_exceeded)
    - Quota exceeded errors
    - Authentication failures caused by expired/revoked keys (401/403)
    - Temporary provider errors (5xx)
    - Connection timeout errors
    """
    # Direct check on Groq SDK exceptions
    if isinstance(exc, (groq.RateLimitError, groq.AuthenticationError, groq.APITimeoutError, groq.APIConnectionError, groq.InternalServerError)):
        return True
        
    # Check status code on generic APIStatusError
    if isinstance(exc, groq.APIStatusError):
        if exc.status_code == 429 or exc.status_code >= 500:
            return True
        if exc.status_code in (401, 403):
            return True
        # 413 from Groq = token rate limit exceeded (TPM) — failover to backup key
        if exc.status_code == 413:
            exc_body = str(exc).lower()
            if "rate_limit_exceeded" in exc_body or "tokens" in exc_body or "too large" in exc_body:
                return True

    # Fallback/broad regex check on exception string representation to be safe
    exc_str = str(exc).lower()
    failover_keywords = [
        "rate limit", "quota exceeded", "timeout", "429", "413", "500", "502", "503", "504",
        "authentication", "api key", "unauthorized", "expired", "revoked", "invalid_api_key",
        "rate_limit_exceeded", "tokens per minute", "tpm", "request too large"
    ]
    if any(keyword in exc_str for keyword in failover_keywords):
        return True

    return False

class FailoverChatGroq(ChatGroq):
    """
    A ChatGroq wrapper/subclass that supports automatic failover between multiple API keys.
    It automatically catches failover-eligible errors from the primary key (API_KEY_1)
    and switches to the backup key (API_KEY_2) seamlessly.
    """
    _backup_models: list = []
    _api_keys: list = []

    def __init__(self, *args, **kwargs):
        # Determine available keys in order of preference
        primary = os.getenv("API_KEY_1") or os.getenv("API_KEY")
        backup = os.getenv("API_KEY_2")
        
        # Build list of active keys
        keys = []
        if primary:
            keys.append(primary)
        if backup and backup != primary:
            keys.append(backup)
            
        if not keys:
            raise ValueError("No API keys found. Please set API_KEY_1 and/or API_KEY_2 in the .env file.")

        # Initialize the base class with the primary key
        kwargs["groq_api_key"] = keys[0]
        super().__init__(*args, **kwargs)
        
        self._api_keys = keys
        
        # Initialize backup ChatGroq instances
        self._backup_models = []
        for key in keys[1:]:
            backup_kwargs = kwargs.copy()
            backup_kwargs["groq_api_key"] = key
            self._backup_models.append(ChatGroq(*args, **backup_kwargs))

    def invoke(self, input: Any, config: Optional[Any] = None, **kwargs: Any) -> Any:
        try:
            logger.info("Attempting LLM invocation using primary API key.")
            response = super().invoke(input, config, **kwargs)
            logger.info("Response successfully generated using primary API key.")
            return response
        except Exception as e:
            if not should_failover(e):
                logger.error(f"Invocation failed with non-failover error: {e}")
                raise e
            
            logger.warning("Primary API key failed. Switching to backup key.")
            
            # Loop through backup models sequentially
            for idx, backup_model in enumerate(self._backup_models):
                try:
                    logger.info(f"Attempting LLM invocation using backup API key {idx + 1}.")
                    response = backup_model.invoke(input, config, **kwargs)
                    logger.info("Response generated using backup key.")
                    return response
                except Exception as backup_err:
                    logger.warning(f"Backup API key {idx + 1} failed. Reason: {backup_err}")
                    if idx == len(self._backup_models) - 1:
                        logger.error("All available API keys have failed.")
                        raise backup_err
            
            # Re-raise original error if there were no backups available
            raise e

    async def ainvoke(self, input: Any, config: Optional[Any] = None, **kwargs: Any) -> Any:
        try:
            logger.info("Attempting async LLM invocation using primary API key.")
            response = await super().ainvoke(input, config, **kwargs)
            logger.info("Async response successfully generated using primary API key.")
            return response
        except Exception as e:
            if not should_failover(e):
                logger.error(f"Async invocation failed with non-failover error: {e}")
                raise e
            
            logger.warning("Primary API key failed in async invocation. Switching to backup key.")
            
            for idx, backup_model in enumerate(self._backup_models):
                try:
                    logger.info(f"Attempting async LLM invocation using backup API key {idx + 1}.")
                    response = await backup_model.ainvoke(input, config, **kwargs)
                    logger.info("Async response generated using backup key.")
                    return response
                except Exception as backup_err:
                    logger.warning(f"Backup API key {idx + 1} failed in async invocation. Reason: {backup_err}")
                    if idx == len(self._backup_models) - 1:
                        logger.error("All available API keys have failed in async invocation.")
                        raise backup_err
            
            raise e
