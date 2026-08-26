class User:
    def greet(self, greeting: str) -> str:
        return f"Hello, {greeting}"


def format_greeting(name: str) -> str:
    return greet_once(name)


def greet_once(name: str) -> str:
    return f"[{name}]"
