from pkg.models import User


def format_greeting(user: User) -> str:
    return "[local] " + user.greet(name="local")


def render(user: User) -> str:
    return format_greeting(user)
