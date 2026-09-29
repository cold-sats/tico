"""Sign-in: which console to open, what to paste in it, and what comes back."""
from __future__ import annotations

from dataclasses import dataclass

from . import contract


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    console_url: str
    steps: tuple[str, ...]


PROVIDERS = {
    "google": Provider("google", "Google", "https://console.cloud.google.com/auth/clients/create", (
        "Pick (or create) a Google Cloud project, and finish the consent screen if it asks (Internal for a Workspace "
        "company, External otherwise).",
        "Application type: Web application. Name it Tico.",
        "Under Authorized redirect URIs add the URI below, exactly, with no trailing slash.",
        "Create, then copy the client ID and client secret.")),
    "microsoft": Provider("microsoft", "Microsoft",
                          "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/CreateApplicationBlade",
                          ("Register an application named Tico; supported account types: this organization only.",
                           "Redirect URI: platform Web, and the URI below, exactly.",
                           "Copy the Application (client) ID and the Directory (tenant) ID from Overview.",
                           "Certificates & secrets > New client secret; copy the secret Value (not the ID).")),
}


def redirect_uri(domain: str) -> str:
    return f"https://{domain}{contract.REDIRECT_PATH}"
