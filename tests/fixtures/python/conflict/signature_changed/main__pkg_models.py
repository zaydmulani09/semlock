class User:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"


def format_greeting(name: str) -> str:
    return greet_once(name)


def greet_once(name: str) -> str:
    return f"[{name}]"
