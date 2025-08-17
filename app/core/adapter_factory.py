from app.config import Settings, get_settings
from app.core.vcs_adapter import VCSAdapter
from app.core.github import GitHubAdapter
from app.core.bitbucket import BitbucketAdapter

def get_vcs_adapter(settings: Settings = get_settings()) -> VCSAdapter:
    if settings.vcs_provider == "github":
        return GitHubAdapter(settings)
    elif settings.vcs_provider == "bitbucket":
        return BitbucketAdapter(settings)
    else:
        raise ValueError(f"Unsupported VCS provider: {settings.vcs_provider}")
