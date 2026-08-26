from pkg import format_greeting
from pkg.impl import User


def welcome(user: User) -> str:
    return format_greeting(user)
