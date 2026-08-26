class User:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"


def format_greeting(name: str) -> str:
    return f"[{name}]"
