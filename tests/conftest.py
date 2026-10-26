"""Shared fixtures for the YNAB Custom tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ynab_custom in every test."""
    yield
