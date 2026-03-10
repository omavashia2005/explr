# test: no user-defined function calls
# expected: no diagram created

x = 10
y = 20
result = x + y
greeting = "hello " + "world"
items = [i * 2 for i in range(5)]
print(result, greeting, items)
