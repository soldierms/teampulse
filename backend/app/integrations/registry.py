from app.integrations.base import DeploySource, IncidentSource
from app.integrations.credentials import decrypt_credentials
from app.integrations.github.provider import GitHubProvider
from app.integrations.mock.provider import MockDeployProvider, MockIncidentProvider
from app.integrations.pagerduty.provider import PagerDutyProvider
from app.models.integration import Integration

INCIDENT_PROVIDERS = {"pagerduty": PagerDutyProvider}
DEPLOY_PROVIDERS = {"github": GitHubProvider}
MOCK_PROVIDERS = {"pagerduty": MockIncidentProvider, "github": MockDeployProvider}


class UnknownProvider(ValueError):
    pass


def build_source(integration: Integration) -> IncidentSource | DeploySource:
    """An integration flagged `mock` in config uses fixture data but the same
    mapper and the same persistence path as its live counterpart."""
    provider = integration.provider
    config = integration.config or {}

    if config.get("mock"):
        factory = MOCK_PROVIDERS.get(provider)
        if factory is None:
            raise UnknownProvider(f"No mock provider for '{provider}'")
        return factory(None, config)

    credentials = decrypt_credentials(integration.credentials)
    factory = INCIDENT_PROVIDERS.get(provider) or DEPLOY_PROVIDERS.get(provider)
    if factory is None:
        raise UnknownProvider(f"No provider registered for '{provider}'")
    return factory(credentials, config)


def is_incident_provider(integration: Integration) -> bool:
    return integration.provider in INCIDENT_PROVIDERS


def is_deploy_provider(integration: Integration) -> bool:
    return integration.provider in DEPLOY_PROVIDERS
