from hello2 import hello_2

def hello():
    print("Hello from original hello.py!")
    hello_2()

def main():
    hello()

if __name__ == "__main__":
    main()