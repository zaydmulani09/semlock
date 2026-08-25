class User:
    def greet(self, name: str, *, punctuation: str = "!") -> str:
        return f"Hello, {name}{punctuation}"


def format_greeting(name: str) -> str:
    return name


def shout(text: str) -> str:
    return text.upper()
