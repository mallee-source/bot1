"""
Admin tool — run this on the server to create customers and manage credits.

Usage:
  python admin.py add <username> <password> <credits>
  python admin.py topup <username> <credits_to_add>
  python admin.py list
"""

import sqlite3
import sys

from app import hash_password, get_db, init_db


def add_user(username, password, credits):
    conn = get_db()
    conn.execute(
        "INSERT INTO users (username, password_hash, credits) VALUES (?, ?, ?)",
        (username, hash_password(password), int(credits)),
    )
    conn.commit()
    conn.close()
    print(f"Created user '{username}' with {credits} credits.")


def topup(username, credits_to_add):
    conn = get_db()
    conn.execute(
        "UPDATE users SET credits = credits + ? WHERE username = ?",
        (int(credits_to_add), username),
    )
    conn.commit()
    conn.close()
    print(f"Added {credits_to_add} credits to '{username}'.")


def list_users():
    conn = get_db()
    rows = conn.execute("SELECT username, credits FROM users").fetchall()
    conn.close()
    for row in rows:
        print(f"{row['username']}: {row['credits']} credits")


if __name__ == "__main__":
    init_db()
    if len(sys.argv) < 2:
        print(__doc__)
    elif sys.argv[1] == "add":
        add_user(sys.argv[2], sys.argv[3], sys.argv[4])
    elif sys.argv[1] == "topup":
        topup(sys.argv[2], sys.argv[3])
    elif sys.argv[1] == "list":
        list_users()
    else:
        print(__doc__)
