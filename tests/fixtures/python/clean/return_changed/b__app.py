from pkg.models import User


def banner(user: User) -> str:
    message: str = user.greet(name="Ada")
    return message.upper()
