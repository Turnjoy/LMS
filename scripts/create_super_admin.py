"""Utility script to create or update a super_admin user and optionally set the master password.

Usage:
  python scripts/create_super_admin.py --email admin@example.com --password secret123

This will create or update a user with role `super_admin` and set the MASTER_ADMIN_PASSWORD
in the local .env file if present. It prints the action taken so you can confirm credentials.
"""
import os
import sys
from pathlib import Path
import argparse

from dotenv import load_dotenv, set_key

# Ensure project root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app, db
from app.models import User


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--email', required=True, help='Super admin email')
    p.add_argument('--password', required=True, help='Password to set for the super admin')
    p.add_argument('--name', default='Turnjoy Owner', help='Full name for the super admin user')
    p.add_argument('--set-master-password', action='store_true', help='Also set MASTER_ADMIN_PASSWORD in .env')
    return p.parse_args()


def main():
    args = parse_args()
    load_dotenv(ROOT / '.env')

    app = create_app('default')
    with app.app_context():
        user = User.query.filter_by(email=args.email.strip().lower()).first()
        if not user:
            user = User(
                name=args.name,
                email=args.email.strip().lower(),
                role='super_admin',
                is_approved=True,
            )
            user.set_password(args.password)
            db.session.add(user)
            db.session.commit()
            print(f'Created super_admin: {user.email}')
        else:
            user.role = 'super_admin'
            user.is_approved = True
            user.set_password(args.password)
            db.session.commit()
            print(f'Updated super_admin: {user.email}')

        if args.set_master_password:
            dotenv_path = ROOT / '.env'
            if dotenv_path.exists():
                set_key(dotenv_path, 'MASTER_ADMIN_PASSWORD', args.password)
                print(f'Set MASTER_ADMIN_PASSWORD in {dotenv_path}')
            else:
                with open(dotenv_path, 'w') as f:
                    f.write(f'MASTER_ADMIN_PASSWORD={args.password}\n')
                print(f'Created {dotenv_path} and set MASTER_ADMIN_PASSWORD')


if __name__ == '__main__':
    main()
