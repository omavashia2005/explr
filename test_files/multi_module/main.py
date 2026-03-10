# test: calls spread across multiple modules (db, auth)
# expected diagram: run -> auth.register -> db.save_user
#                         auth.register -> db.get_user
#                   run -> auth.login    -> db.get_user
#                   run -> report        -> db.all_users

from auth import register, login
from db import all_users

def report():
    users = all_users()
    print(f"Registered users: {len(users)}")
    for u in users:
        print(f"  - {u['name']}")

def run():
    register("u1", "Alice", "pass1")
    register("u2", "Bob",   "pass2")
    login("u1", "pass1")
    report()

if __name__ == "__main__":
    run()
