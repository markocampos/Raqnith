import pytest

from apps.payments.tests.helpers import make_mock_client


@pytest.fixture
def mock_client_factory():
    """Return make_mock_client so pytest tests can build a mock-backed client."""
    return make_mock_client
