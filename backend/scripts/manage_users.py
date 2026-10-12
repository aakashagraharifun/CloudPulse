"""Create an admin or reset a password from the command line (account recovery).

Usage (from the backend directory, with the virtualenv active):
    python -m scripts.manage_users create-admin --email you@example.com --name "Your Name"
    python -m scripts.manage_users reset-password --email you@example.com

In Docker:
    docker compose exec api python -m scripts.manage_users reset-password --email you@example.com

The password is read from the CLOUDPULSE_PASSWORD environment variable if set,
otherwise prompted for (never pass it as a command-line argument: it would be
stored in shell history).
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.core.errors import AppError
from app.db.session import get_sessionmaker
from app.models import User, UserRole
from app.services.audit import record_audit
from app.services.auth import service as auth


def read_password() -> str:
    from_env = os.environ.get("CLOUDPULSE_PASSWORD")
    if from_env:
        return from_env
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudPulse user recovery tool")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-admin", help="Create a new admin user")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    reset = commands.add_parser("reset-password", help="Set a new password and unlock a user")
    reset.add_argument("--email", required=True)
    args = parser.parse_args()

    password = read_password()
    with get_sessionmaker()() as db:
        try:
            if args.command == "create-admin":
                user = auth.create_user(
                    db, email=args.email, name=args.name, password=password, role=UserRole.ADMIN
                )
                record_audit(
                    db,
                    "user.created",
                    actor=None,
                    actor_email="cli",
                    target_type="user",
                    target_id=user.id,
                    details={"email": user.email, "role": user.role, "via": "cli"},
                )
                message = f"Created admin {user.email}."
            else:
                user = db.scalar(select(User).where(User.email == auth.normalize_email(args.email)))
                if user is None:
                    sys.exit(f"No user with email {args.email}.")
                auth.set_password(db, user, password)
                user.is_active = True
                revoked = auth.revoke_user_sessions(db, user.id)
                record_audit(
                    db,
                    "user.password_reset",
                    actor=None,
                    actor_email="cli",
                    target_type="user",
                    target_id=user.id,
                    details={"sessions_revoked": revoked, "via": "cli"},
                )
                message = f"Password reset for {user.email}; {revoked} session(s) signed out."
            db.commit()
        except AppError as exc:
            sys.exit(exc.message)
    print(message)


if __name__ == "__main__":
    main()
