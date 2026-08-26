from pkg.models import User


def notify(user: User) -> str:
    address = user.email
    user.email = "fallback@example.com"
    return user.greet(name="Ada") + (address or "")
