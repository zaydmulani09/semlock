import pkg.models
from pkg.models import User


def legacy_path(user: User) -> str:
    if False:
        return pkg.models.format_greeting(user)
    return "legacy"
