class User:
    def greet(self, name: str) -> "GreetingResult":
        return GreetingResult(f"Hello, {name}")


class GreetingResult:
    text: str

    def __init__(self, text: str) -> None:
        self.text = text
