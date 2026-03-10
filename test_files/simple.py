# test: simple linear call chain
# expected diagram: main -> greet -> format_name

def format_name(first, last):
    return f"{first.title()} {last.title()}"

def greet(first, last):
    name = format_name(first, last)
    print(f"Hello, {name}!")

def main():
    greet("alice", "smith")
    greet("bob", "jones")

if __name__ == "__main__":
    main()
