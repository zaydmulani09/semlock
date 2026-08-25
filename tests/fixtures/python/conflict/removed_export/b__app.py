from pkg.models import User, format_greeting


def welcome(user: User) -> str:
    return format_greeting(user.greet(name="Ada"))
