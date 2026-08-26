from pkg.impl import User


def format_greeting(user: User) -> str:
    return user.greet(name="user")
