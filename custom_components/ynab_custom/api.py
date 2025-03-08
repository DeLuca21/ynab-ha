"""YNAB API Handler."""

import aiohttp
import logging

_LOGGER = logging.getLogger(__name__)

class YNABApi:
    """YNAB API class for handling requests."""

    BASE_URL = "https://api.youneedabudget.com/v1"

    def __init__(self, access_token: str):
        """Initialize the API client."""
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}"}

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

        try:
            # Fetch the data
            response = await self._get(url)

            # Log the response data
            _LOGGER.debug(f"Response for {url}: {response}")

            # If response contains data, return it
            if response:
                return response
            else:
                _LOGGER.warning(f"No data found for {current_month} in budget: {budget_id}")
                return {}
        except Exception as e:
            # Log any errors during the request
            _LOGGER.error(f"Error fetching monthly summary for {current_month}: {e}")
            return {}

    async def _get(self, url: str):
        """Generic GET request handler."""
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self.headers) as response:
                if response.status == 200:
                    # If the response is successful, return the data
                    data = await response.json()
                    return data.get("data", {})
                else:
                    # Log if the request fails
                    _LOGGER.error("YNAB API error: %s - URL: %s", response.status, url)
                    return {}
