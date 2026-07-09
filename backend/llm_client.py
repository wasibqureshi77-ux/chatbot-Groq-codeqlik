import os
import logging
import contextvars
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import groq
from langchain_groq import ChatGroq
from config import API_KEY_1, API_KEY_2, API_KEY

thread_id_var = contextvars.ContextVar("thread_id", default="unknown")
node_name_var = contextvars.ContextVar("node_name", default="general")

MODEL_COSTS = {
    "default": {"input_cost_per_million": 0.15, "output_cost_per_million": 0.60},
    "llama3-70b": {"input_cost_per_million": 0.59, "output_cost_per_million": 0.79},
    "llama-3.1-70b-versatile": {"input_cost_per_million": 0.59, "output_cost_per_million": 0.79},
    "llama3-8b": {"input_cost_per_million": 0.05, "output_cost_per_million": 0.08},
    "llama-3.1-8b-instant": {"input_cost_per_million": 0.05, "output_cost_per_million": 0.08},
    "mixtral-8x7b-32768": {"input_cost_per_million": 0.24, "output_cost_per_million": 0.24},
    "gemma2-9b-it": {"input_cost_per_million": 0.20, "output_cost_per_million": 0.20},
    "gpt-oss-120b": {"input_cost_per_million": 0.15, "output_cost_per_million": 0.60},
    "gpt-oss-20b": {"input_cost_per_million": 0.075, "output_cost_per_million": 0.30},
    "compound-mini": {"input_cost_per_million": 0.015, "output_cost_per_million": 0.03},
    "qwen3.6-27b": {"input_cost_per_million": 0.10, "output_cost_per_million": 0.15},
    "qwen3-32b": {"input_cost_per_million": 0.12, "output_cost_per_million": 0.18},
    "llama-prompt-guard-2-86m": {"input_cost_per_million": 0.005, "output_cost_per_million": 0.005},
}

def get_model_cost_rates(model: str):
    model_lower = (model or "").strip().lower()
    model_short = model_lower.split("/")[-1] if model_lower else ""

    for key, rates in sorted(MODEL_COSTS.items(), key=lambda item: len(item[0]), reverse=True):
        key_lower = key.lower()
        if key_lower == "default":
            continue
        if model_lower == key_lower or model_short == key_lower or key_lower in model_lower:
            return key, rates

    return "default", MODEL_COSTS["default"]

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    _, rates = get_model_cost_rates(model)
    input_cost = (input_tokens / 1_000_000) * rates["input_cost_per_million"]
    output_cost = (output_tokens / 1_000_000) * rates["output_cost_per_million"]
    return input_cost + output_cost

def get_llm_model_name(llm: Any) -> str:
    for attr in ("model", "model_name"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)
    return "unknown"

def log_llm_call(model: str, response: Any, latency: float):
    try:
        from database import llm_usage_logs_collection
        
        input_tokens = 0
        output_tokens = 0
        
        usage = getattr(response, "usage_metadata", None) or {}
        if usage:
            input_tokens = usage.get("input_tokens") or 0
            output_tokens = usage.get("output_tokens") or 0
            
        if not input_tokens and hasattr(response, "response_metadata"):
            token_usage = response.response_metadata.get("token_usage") or {}
            input_tokens = token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
            output_tokens = token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
            
        total_tokens = input_tokens + output_tokens
        cost_model, rates = get_model_cost_rates(model)
        cost = calculate_cost(model, input_tokens, output_tokens)
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc),
            "thread_id": thread_id_var.get("unknown"),
            "model": model,
            "cost_model": cost_model,
            "input_cost_per_million": rates["input_cost_per_million"],
            "output_cost_per_million": rates["output_cost_per_million"],
            "node": node_name_var.get("general"),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency": round(latency, 3),
            "cost": round(cost, 8)
        }
        
        llm_usage_logs_collection.insert_one(log_entry)
        logger.info(f"[LLM Usage Log] Logged node={log_entry['node']} model={model} rate={cost_model} tokens={total_tokens} cost={log_entry['cost']:.6f} latency={log_entry['latency']}s")
    except Exception as e:
        logger.error(f"Failed to log LLM usage: {e}")

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
        keys = []
        
        # Check API_KEY_1 or API_KEY first
        primary = os.getenv("API_KEY_1") or os.getenv("API_KEY")
        if primary:
            keys.append(primary)
            
        # Check other API keys (API_KEY_2 up to API_KEY_10)
        for i in range(2, 11):
            key = os.getenv(f"API_KEY_{i}")
            if key and key not in keys:
                keys.append(key)
            
        if not keys:
            raise ValueError("No API keys found. Please set API_KEY_1 or other API keys in the .env file.")

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
        start_time = time.time()
        response = None
        try:
            logger.info("Attempting LLM invocation using primary API key.")
            response = super().invoke(input, config, **kwargs)
            logger.info("Response successfully generated using primary API key.")
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
                    break
                except Exception as backup_err:
                    logger.warning(f"Backup API key {idx + 1} failed. Reason: {backup_err}")
                    if idx == len(self._backup_models) - 1:
                        logger.error("All available API keys have failed.")
                        raise backup_err
            
            if response is None:
                raise e

        latency = time.time() - start_time
        log_llm_call(get_llm_model_name(self), response, latency)
        return response

    async def ainvoke(self, input: Any, config: Optional[Any] = None, **kwargs: Any) -> Any:
        start_time = time.time()
        response = None
        try:
            logger.info("Attempting async LLM invocation using primary API key.")
            response = await super().ainvoke(input, config, **kwargs)
            logger.info("Async response successfully generated using primary API key.")
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
                    break
                except Exception as backup_err:
                    logger.warning(f"Backup API key {idx + 1} failed in async invocation. Reason: {backup_err}")
                    if idx == len(self._backup_models) - 1:
                        logger.error("All available API keys have failed in async invocation.")
                        raise backup_err
            
            if response is None:
                raise e

        latency = time.time() - start_time
        log_llm_call(get_llm_model_name(self), response, latency)
        return response
