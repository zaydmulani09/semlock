class User:
    def __init__(self, email: str | None = None) -> None:
        self.email = email

    def greet(self, name: str) -> str:
        return f"Hello, {name}"
