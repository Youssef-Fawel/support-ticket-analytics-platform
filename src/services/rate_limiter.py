"""
Task 10: Rate Limiter service.

Client-side rate limiter to enforce the external API's rate limit.

Requirements:
1. Respect a limit of 60 requests per minute.
2. When a 429 response is returned, wait for the `Retry-After` duration before retrying.
3. Enforce a global limit even when multiple tenants are ingesting concurrently.

Implementation notes:
- Implement a token bucket or sliding window algorithm.
- You may use external rate limiting libraries.
"""

import asyncio
import time
from typing import Optional
from collections import deque


class RateLimiter:
    """
    Sliding window rate limiter.

    Limits the number of allowed requests per minute.
    """

    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60
        self.request_times: deque = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """
        Acquire permission to perform a request.

        Returns:
            The number of seconds to wait before performing the request.
            Returns 0 if the request can proceed immediately.

        Inspects the number of requests in the current window.
        If the limit is exceeded, computes how long to wait.
        Thread-safe using asyncio.Lock.
        """
        async with self._lock:
            now = time.time()
            
            # Remove requests outside the current window
            while self.request_times and now - self.request_times[0] > self.window_seconds:
                self.request_times.popleft()
            
            # Check if we can make a request
            if len(self.request_times) < self.requests_per_minute:
                # We can proceed immediately
                self.request_times.append(now)
                return 0
            else:
                # Need to wait until the oldest request expires
                oldest_request = self.request_times[0]
                wait_time = self.window_seconds - (now - oldest_request)
                return max(0, wait_time)

    async def wait_and_acquire(self) -> None:
        """
        Acquire permission to perform a request, waiting if necessary.

        If the rate limit has been reached, this method will sleep
        until a request can be issued.
        """
        wait_time = await self.acquire()
        if wait_time > 0:
            await asyncio.sleep(wait_time)
            # After waiting, try to acquire again (should succeed now)
            await self.wait_and_acquire()

    def get_status(self) -> dict:
        """
        Return the current status of the rate limiter.

        Returns:
            {
                "limit": int,
                "window_seconds": int,
                "current_requests": int,
                "remaining": int
            }
        """
        now = time.time()
        # Drop any requests that are outside of the current window.
        while self.request_times and now - self.request_times[0] > self.window_seconds:
            self.request_times.popleft()

        current = len(self.request_times)
        return {
            "limit": self.requests_per_minute,
            "window_seconds": self.window_seconds,
            "current_requests": current,
            "remaining": max(0, self.requests_per_minute - current)
        }


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter (alternative implementation).

    Uses a token bucket algorithm to control request rate.
    """

    def __init__(self, tokens_per_second: float = 1.0, bucket_size: int = 60):
        self.tokens_per_second = tokens_per_second
        self.bucket_size = bucket_size
        self.tokens = bucket_size
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """
        Attempt to acquire a token.

        Returns:
            The number of seconds to wait before a token is available.
            Returns 0 if a token can be taken immediately.

        Refills tokens based on elapsed time.
        If at least one token is available, consumes it and returns 0.
        If no tokens are available, computes how long until the next token.
        """
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            
            # Refill tokens based on elapsed time
            self.tokens = min(
                self.bucket_size,
                self.tokens + (elapsed * self.tokens_per_second)
            )
            self.last_update = now
            
            if self.tokens >= 1.0:
                # Token available, consume it
                self.tokens -= 1.0
                return 0
            else:
                # No tokens available, compute wait time
                tokens_needed = 1.0 - self.tokens
                wait_time = tokens_needed / self.tokens_per_second
                return wait_time

    async def wait_and_acquire(self) -> None:
        """
        Acquire a token, waiting if necessary.
        """
        wait_time = await self.acquire()
        if wait_time > 0:
            await asyncio.sleep(wait_time)
            # Try again after waiting
            await self.wait_and_acquire()


# Global RateLimiter singleton instance.
_global_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Return the global RateLimiter instance."""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimiter(requests_per_minute=60)
    return _global_rate_limiter
