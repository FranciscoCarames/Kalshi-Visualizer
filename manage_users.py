"""Admin CLI for per-user auth accounts — ``python -m manage_users <command>``.

The ONLY way to create/modify accounts (there is no self-signup). Passwords are read with ``getpass`` so
they are never echoed to the terminal or shell history, and never logged. This module is a boundary, so it
reads ``AUTH_DB_PATH`` from the environment here (``config`` stays import-free); every store call passes the
resolved path explicitly.

Commands:
    add <username>           create a user (prompts for password twice; --force-pw-change to require a reset)
    passwd <username>        change a user's password (logs every other device out)
    list                     list users (username, disabled, locked, force-pw-change)
    disable <username>       disable an account (revokes its live sessions + device tokens)
    enable <username>        re-enable an account
    unlock <username>        clear a brute-force lockout (admin recovery)
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
import time

import auth_store
import config

# Password policy is single-sourced in auth_store (shared with the env seed + self-service change).
validate_password_strength = auth_store.validate_password_strength


def _auth_db_path() -> str:
    """Resolve AUTH_DB_PATH from the env at this boundary (config stays import-free)."""
    return os.getenv("AUTH_DB_PATH", config.AUTH_DB_PATH)


def _prompt_new_password() -> str:
    pw = getpass.getpass("New password: ")
    err = validate_password_strength(pw)
    if err:
        sys.exit(f"error: {err}")
    if pw != getpass.getpass("Confirm password: "):
        sys.exit("error: passwords do not match")
    return pw


def cmd_add(args: argparse.Namespace) -> None:
    db = _auth_db_path()
    pw = _prompt_new_password()
    try:
        auth_store.create_user(args.username, pw, now=time.time(),
                               force_pw_change=args.force_pw_change, db_path=db)
    except ValueError as exc:
        sys.exit(f"error: {exc}")
    print(f"created user {args.username!r}"
          + (" (must change password at next login)" if args.force_pw_change else ""))


def cmd_passwd(args: argparse.Namespace) -> None:
    db = _auth_db_path()
    if auth_store.get_user(args.username, db_path=db) is None:
        sys.exit(f"error: no such user: {args.username!r}")
    pw = _prompt_new_password()
    auth_store.set_password(args.username, pw, now=time.time(), db_path=db)
    print(f"password updated for {args.username!r} (other devices signed out)")


def cmd_list(_args: argparse.Namespace) -> None:
    db = _auth_db_path()
    users = auth_store.list_users(db_path=db)
    if not users:
        print("(no users — seed one with `python -m manage_users add <username>`)")
        return
    now = time.time()
    print(f"{'username':<24} {'disabled':<9} {'locked':<7} {'force_pw_change':<15}")
    for u in users:
        locked = "yes" if auth_store.is_locked(u, now=now) else "no"
        print(f"{u['username']:<24} {('yes' if u['disabled'] else 'no'):<9} {locked:<7} "
              f"{('yes' if u['force_pw_change'] else 'no'):<15}")


def cmd_disable(args: argparse.Namespace) -> None:
    db = _auth_db_path()
    try:
        auth_store.set_disabled(args.username, True, now=time.time(), db_path=db)
    except ValueError as exc:
        sys.exit(f"error: {exc}")
    print(f"disabled {args.username!r} (live sessions + device tokens revoked)")


def cmd_enable(args: argparse.Namespace) -> None:
    db = _auth_db_path()
    try:
        auth_store.set_disabled(args.username, False, now=time.time(), db_path=db)
    except ValueError as exc:
        sys.exit(f"error: {exc}")
    print(f"enabled {args.username!r}")


def cmd_unlock(args: argparse.Namespace) -> None:
    db = _auth_db_path()
    auth_store.unlock(args.username, db_path=db)
    print(f"cleared lockout for {args.username!r}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="manage_users", description="Manage per-user auth accounts.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="create a user")
    p_add.add_argument("username")
    p_add.add_argument("--force-pw-change", action="store_true",
                       help="require the user to set a new password at first login")
    p_add.set_defaults(func=cmd_add)

    p_passwd = sub.add_parser("passwd", help="change a user's password")
    p_passwd.add_argument("username")
    p_passwd.set_defaults(func=cmd_passwd)

    p_list = sub.add_parser("list", help="list users")
    p_list.set_defaults(func=cmd_list)

    p_disable = sub.add_parser("disable", help="disable an account")
    p_disable.add_argument("username")
    p_disable.set_defaults(func=cmd_disable)

    p_enable = sub.add_parser("enable", help="re-enable an account")
    p_enable.add_argument("username")
    p_enable.set_defaults(func=cmd_enable)

    p_unlock = sub.add_parser("unlock", help="clear a brute-force lockout")
    p_unlock.add_argument("username")
    p_unlock.set_defaults(func=cmd_unlock)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
