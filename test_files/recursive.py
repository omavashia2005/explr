# test: recursive functions
# expected diagram: main -> fibonacci -> fibonacci (self-loop), main -> factorial -> factorial

def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

def main():
    print(factorial(6))
    print(fibonacci(7))

if __name__ == "__main__":
    main()
