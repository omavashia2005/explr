# test: class methods
# expected diagram: run -> Cart.add_item -> Cart.total -> Cart.apply_discount

class Cart:
    def __init__(self):
        self.items = []

    def add_item(self, name, price):
        self.items.append({"name": name, "price": price})

    def total(self):
        return sum(i["price"] for i in self.items)

    def apply_discount(self, pct):
        t = self.total()
        return t * (1 - pct / 100)


def run():
    cart = Cart()
    cart.add_item("apple", 1.20)
    cart.add_item("bread", 2.50)
    cart.add_item("milk", 0.99)
    discounted = cart.apply_discount(10)
    print(f"Total after 10% discount: £{discounted:.2f}")


if __name__ == "__main__":
    run()
