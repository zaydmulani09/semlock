class User:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"


def format_greeting(user: User) -> str:
    return user.greet(name="user")
