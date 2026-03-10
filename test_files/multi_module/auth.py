from db import save_user, get_user

def register(user_id, name, password):
    if get_user(user_id):
        raise ValueError(f"User {user_id} already exists")
    save_user(user_id, {"name": name, "password": password})

def login(user_id, password):
    user = get_user(user_id)
    if not user or user["password"] != password:
        raise ValueError("Invalid credentials")
    return user
