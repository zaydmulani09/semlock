from pkg.models import User, format_greeting


def welcome(user: User) -> str:
    message = user.greet(name="Ada")
    return format_greeting(message)
