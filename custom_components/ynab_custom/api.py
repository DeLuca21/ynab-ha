"""YNAB API Handler."""

import aiohttp
import asyncio
import logging
from datetime import datetime, timedelta
from collections import deque

_LOGGER = logging.getLogger(__name__)


class YNABApiError(Exception):
    """Raised when a YNAB write request is rejected."""


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

        # Track this request
        self._track_request()
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", {})
                elif response.status == 404:
                    # Month doesn't exist yet - this is normal for future months
                    _LOGGER.debug(f"Month {current_month} not found (404) - may not exist yet in budget: {budget_id}")
                    return {}
                elif response.status == 429:
                    # Let 429 errors propagate to coordinator
                    raise Exception(f"429 - Too Many Requests: {url}")
                else:
                    _LOGGER.warning(f"YNAB API error: {response.status} - URL: {url}")
                    return {}

    async def get_transactions(self, budget_id: str, last_knowledge_of_server=None):
        """Fetch transactions for a specific budget.

        When last_knowledge_of_server is supplied, YNAB returns only the
        transactions that have changed since that point (including tombstones
        for deleted ones) rather than the default one-year window. The caller
        is responsible for merging the delta into its own cache.
        """
        if not budget_id or budget_id == "budgets":
            _LOGGER.error("Invalid budget_id before transactions API call: %s", budget_id)
            return {}

        url = f"{self.BASE_URL}/budgets/{budget_id}/transactions"
        if last_knowledge_of_server:
            url = f"{url}?last_knowledge_of_server={last_knowledge_of_server}"
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

    async def get_month_category(self, budget_id: str, category_id: str, month: str = "current"):
        """Fetch one category's figures for a month ("current" or YYYY-MM-01)."""
        url = f"{self.BASE_URL}/budgets/{budget_id}/months/{month}/categories/{category_id}"
        data = await self._request("GET", url)
        return data.get("category", {})

    async def set_month_category_budgeted(self, budget_id: str, category_id: str, budgeted: int, month: str = "current"):
        """Set the assigned (budgeted) amount, in milliunits, for a category in a month.

        YNAB takes the new total rather than a delta, so callers read the
        current value first and write back the adjusted figure.
        """
        url = f"{self.BASE_URL}/budgets/{budget_id}/months/{month}/categories/{category_id}"
        data = await self._request("PATCH", url, {"category": {"budgeted": budgeted}})
        return data.get("category", {})

    async def get_month(self, budget_id: str, month: str = "current"):
        """Fetch a budget month, including to_be_budgeted (Ready to Assign)."""
        url = f"{self.BASE_URL}/budgets/{budget_id}/months/{month}"
        data = await self._request("GET", url)
        return data.get("month", {})

    async def get_account(self, budget_id: str, account_id: str):
        """Fetch a single account, including its transfer_payee_id."""
        url = f"{self.BASE_URL}/budgets/{budget_id}/accounts/{account_id}"
        data = await self._request("GET", url)
        return data.get("account", {})

    async def create_transaction(self, budget_id: str, transaction: dict):
        """Create a single transaction and return it."""
        url = f"{self.BASE_URL}/budgets/{budget_id}/transactions"
        data = await self._request("POST", url, {"transaction": transaction})
        return data.get("transaction", {})

    async def _request(self, method: str, url: str, payload: dict = None):
        """Request handler for calls that must not fail silently.

        Unlike _get, errors raise YNABApiError carrying YNAB's own error
        detail, so a money movement that did not happen is never reported
        as done.
        """
        self._track_request()

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.request(method, url, headers=self.headers, json=payload) as response:
                    if response.status in (200, 201):
                        data = await response.json()
                        return data.get("data", {})

                    try:
                        error = (await response.json()).get("error", {})
                        detail = error.get("detail") or error.get("name") or ""
                    except Exception:
                        detail = ""
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("YNAB API request failed: %s - %s %s", err, method, url)
            raise YNABApiError(f"request failed: {err or type(err).__name__}") from err

        _LOGGER.error("YNAB API error: %s %s - %s %s", response.status, detail, method, url)
        raise YNABApiError(f"{response.status} - {detail}".strip(" -"))
