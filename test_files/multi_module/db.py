USERS = {}

def save_user(user_id, data):
    USERS[user_id] = data

def get_user(user_id):
    return USERS.get(user_id)

def all_users():
    return list(USERS.values())
