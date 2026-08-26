from pkg.models import User


def welcome(user: User) -> str:
    message = user.greet(name="Ada")
    return message.upper()
