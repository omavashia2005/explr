# test: conditional branches — both paths should appear in the diagram
# expected diagram: process -> validate
#                   process -> handle_even / handle_odd
#                   run     -> process (called multiple times)

def validate(n):
    if not isinstance(n, int):
        raise TypeError(f"Expected int, got {type(n).__name__}")
    return True

def handle_even(n):
    print(f"{n} is even → {n // 2}")

def handle_odd(n):
    print(f"{n} is odd  → {n * 3 + 1}")

def process(n):
    validate(n)
    if n % 2 == 0:
        handle_even(n)
    else:
        handle_odd(n)

def run():
    for n in [4, 7, 12, 3, 8]:
        process(n)

if __name__ == "__main__":
    run()
