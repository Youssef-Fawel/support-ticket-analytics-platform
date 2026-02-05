import httpx
import asyncio
import random
from src.core.logging import logger
from src.services.circuit_breaker import get_circuit_breaker, CircuitBreakerOpenError

class NotifyService:
    def __init__(self):
        self.notify_url = "http://mock-external-api:9000/notify"
        self.circuit_breaker = get_circuit_breaker("notify")
        self.max_retries = 3
        self.base_delay = 1.0  # seconds

    async def send_notification(self, ticket_id: str, tenant_id: str, urgency: str, reason: str):
        """
        Sends a notification to the external service with manual retry logic.
        
        Implements exponential backoff using asyncio.sleep (no external retry libraries).
        Uses circuit breaker to fail fast when the service is consistently down.
        Does not block the main ingestion flow - failures are logged but don't raise.
        """
        payload = {
            "ticket_id": ticket_id,
            "tenant_id": tenant_id,
            "urgency": urgency,
            "reason": reason
        }

        # Run notification asynchronously without blocking
        asyncio.create_task(self._send_with_retry(payload))

    async def _send_with_retry(self, payload: dict) -> bool:
        """
        Internal method to send notification with manual retry logic.
        
        Returns True if successful, False otherwise.
        Does not raise exceptions - logs failures instead.
        """
        for attempt in range(self.max_retries):
            try:
                # Check circuit breaker status
                try:
                    result = await self.circuit_breaker.call(self._make_request, payload)
                    logger.info(f"Notification sent successfully for ticket {payload['ticket_id']}")
                    return True
                except CircuitBreakerOpenError as e:
                    logger.warning(
                        f"Circuit breaker is OPEN for notifications. "
                        f"Retry after {e.retry_after:.1f}s. Ticket: {payload['ticket_id']}"
                    )
                    return False

            except Exception as e:
                logger.error(
                    f"Notification attempt {attempt + 1}/{self.max_retries} failed "
                    f"for ticket {payload['ticket_id']}: {str(e)}"
                )
                
                if attempt < self.max_retries - 1:
                    # Exponential backoff: 1s, 2s, 4s
                    delay = self.base_delay * (2 ** attempt)
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0, 0.3 * delay)
                    await asyncio.sleep(delay + jitter)
                else:
                    logger.error(
                        f"All {self.max_retries} notification attempts failed "
                        f"for ticket {payload['ticket_id']}"
                    )
        
        return False

    async def _make_request(self, payload: dict):
        """
        Make the actual HTTP request to the notification endpoint.
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(self.notify_url, json=payload)
            response.raise_for_status()
            return response.json()
