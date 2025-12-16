"""YNAB API Handler."""

import aiohttp
import logging
from datetime import datetime, timedelta
from collections import deque

_LOGGER = logging.getLogger(__name__)

class YNABApi:
    """YNAB API class for handling requests."""

    BASE_URL = "https://api.youneedabudget.com/v1"

    def __init__(self, access_token: str, shared_tracking: dict = None):
        """Initialize the API client."""
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}"}
        
        # Use shared request tracking if provided, otherwise create local tracking
        if shared_tracking:
            self.request_timestamps = shared_tracking["request_timestamps"]
            self._shared_tracking = shared_tracking  # Keep reference for shared counter
        else:
            # Fallback to local tracking (for backwards compatibility)
            self.request_timestamps = deque()
            self._shared_tracking = None

    def _track_request(self):
        """Track a new API request with timestamp."""
        now = datetime.now()
        self.request_timestamps.append(now)
        
        # Update shared total counter (cumulative across all instances)
        if self._shared_tracking:
            self._shared_tracking["total_requests"] += 1  # Increment shared counter
        else:
            # Fallback for local tracking
            if not hasattr(self, 'total_requests'):
                self.total_requests = 0
            self.total_requests += 1
        
        # Clean old requests (older than 1 hour)
        cutoff_time = now - timedelta(hours=1)
        cleaned_count = 0
        while self.request_timestamps and self.request_timestamps[0] < cutoff_time:
            self.request_timestamps.popleft()
            cleaned_count += 1
        

    def get_rate_limit_info(self):
        """Get current rate limit status and statistics."""
        now = datetime.now()
        
        # Clean old requests first
        cutoff_time = now - timedelta(hours=1)
        while self.request_timestamps and self.request_timestamps[0] < cutoff_time:
            self.request_timestamps.popleft()
        
        requests_this_hour = len(self.request_timestamps)
        estimated_remaining = max(0, 200 - requests_this_hour)
        
        # Calculate when the rate limit resets (1 hour from oldest request)
        if self.request_timestamps:
            oldest_request = self.request_timestamps[0]
            rate_limit_resets_at = oldest_request + timedelta(hours=1)
        else:
            rate_limit_resets_at = now + timedelta(hours=1)
        
        return {
            "requests_made_total": self._shared_tracking["total_requests"] if self._shared_tracking else getattr(self, 'total_requests', 0),
            "requests_this_hour": requests_this_hour,
            "estimated_remaining": estimated_remaining,
            "rate_limit_resets_at": rate_limit_resets_at.strftime("%I:%M %p"),
        }

    async def get_budgets(self):
        """Fetch available budgets."""
        url = f"{self.BASE_URL}/budgets"
        _LOGGER.debug("Fetching budgets from URL: %s", url)
        return await self._get(url)

    async def get_budget(self, budget_id: str):
        """Fetch full details for a specific budget."""
        if not budget_id or budget_id == "budgets":
            _LOGGER.error("Invalid budget_id before API call: %s", budget_id)
            return {}

        url = f"{self.BASE_URL}/budgets/{budget_id}"
        _LOGGER.debug("Fetching budget from URL: %s", url)
        return await self._get(url)

    async def get_accounts(self, budget_id: str):
        """Fetch accounts for a specific budget."""
        if not budget_id or budget_id == "budgets":
            _LOGGER.error("Invalid budget_id before accounts API call: %s", budget_id)
            return {}

        url = f"{self.BASE_URL}/budgets/{budget_id}/accounts"
        _LOGGER.debug("Fetching accounts from URL: %s", url)
        return await self._get(url)

    async def get_categories(self, budget_id: str):
        """Fetch categories for a specific budget."""
        if not budget_id or budget_id == "budgets":
            _LOGGER.error("Invalid budget_id before categories API call: %s", budget_id)
            return {}

        url = f"{self.BASE_URL}/budgets/{budget_id}/categories"
        _LOGGER.debug("Fetching categories from URL: %s", url)
        return await self._get(url)

    async def get_monthly_summary(self, budget_id: str, current_month: str):
        """Fetch the latest monthly summary for a specific budget."""
        if not budget_id or budget_id == "budgets":
            _LOGGER.error("Invalid budget_id before months API call: %s", budget_id)
            return {}

        # Form the URL to query the specific month
        url = f"{self.BASE_URL}/budgets/{budget_id}/months/{current_month}"  # Include the full date with day
        _LOGGER.debug(f"Requesting URL: {url}")  # Log the full URL being requested

        # Fetch the data - let 429 errors propagate to coordinator
        response = await self._get(url)

        # Log the response data
        _LOGGER.debug(f"Response for {url}: {response}")

        # If response contains data, return it
        if response:
            return response
        else:
            _LOGGER.warning(f"No data found for {current_month} in budget: {budget_id}")
            return {}

    async def get_transactions(self, budget_id: str):
        """Fetch recent transactions for a specific budget."""
        if not budget_id or budget_id == "budgets":
            _LOGGER.error("Invalid budget_id before transactions API call: %s", budget_id)
            return {}

        url = f"{self.BASE_URL}/budgets/{budget_id}/transactions"
        _LOGGER.debug("Fetching transactions from URL: %s", url)
        return await self._get(url)

    async def _get(self, url: str):
        """Generic GET request handler."""
        # Track this request
        self._track_request()
        
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    # If the response is successful, return the data
                    data = await response.json()
                    return data.get("data", {})
                else:
                    # Log if the request fails
                    _LOGGER.error("YNAB API error: %s - URL: %s", response.status, url)
                    
                    # Raise exception for 429 errors so coordinator can catch them
                    if response.status == 429:
                        raise Exception(f"429 - Too Many Requests: {url}")
                    
                    return {}
