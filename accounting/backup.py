#!/usr/bin/env python3
"""Accounting system backup script.

Creates timestamped backups of all accounting data and cleans old backups.
Designed to be run daily via cron/launchd.

Usage:
    python3 backup.py          # Run backup
    python3 backup.py --list   # List available backups
"""

import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

ACCOUNTING_DIR = '/Users/aitree414/Accounting'
PROJECTS_DIR = os.path.join(ACCOUNTING_DIR, 'projects')
AUTH_FILE = os.path.join(ACCOUNTING_DIR, '.accounting.auth')
SUPPLIERS_FILE = os.path.join(ACCOUNTING_DIR, 'suppliers.json')
RATES_FILE = os.path.join(ACCOUNTING_DIR, 'exchange_rates.json')
BACKUP_DIR = os.path.join(ACCOUNTING_DIR, 'backups')
RETENTION_DAYS = 30
TZ_HK = timezone(timedelta(hours=8))


def list_backups():
    """List available backups."""
    if not os.path.exists(BACKUP_DIR):
        print("No backups found.")
        return
    backups = sorted(os.listdir(BACKUP_DIR), reverse=True)
    for d in backups:
        dpath = os.path.join(BACKUP_DIR, d)
        if os.path.isdir(dpath):
            file_count = sum(len(files) for _, _, files in os.walk(dpath))
            print(f"  {d}  ({file_count} files)")


def run_backup():
    """Create a timestamped backup of all accounting data."""
    now = datetime.now(TZ_HK)
    date_str = now.strftime('%Y-%m-%d')
    backup_path = os.path.join(BACKUP_DIR, date_str)
    os.makedirs(backup_path, exist_ok=True)

    # Copy auth file
    if os.path.exists(AUTH_FILE):
        shutil.copy2(AUTH_FILE, os.path.join(backup_path, '.accounting.auth'))

    # Copy data files
    for fname in ('suppliers.json', 'exchange_rates.json'):
        fpath = os.path.join(ACCOUNTING_DIR, fname)
        if os.path.exists(fpath):
            shutil.copy2(fpath, os.path.join(backup_path, fname))

    # Copy project directories
    if os.path.exists(PROJECTS_DIR):
        for proj_name in os.listdir(PROJECTS_DIR):
            proj_dir = os.path.join(PROJECTS_DIR, proj_name)
            if not os.path.isdir(proj_dir):
                continue
            proj_backup = os.path.join(backup_path, proj_name)
            os.makedirs(proj_backup, exist_ok=True)
            # Copy project files
            for fname in ('transactions.csv', 'project.json'):
                src = os.path.join(proj_dir, fname)
                if os.path.exists(src):
                    shutil.copy2(src, os.path.join(proj_backup, fname))
            # Copy files directory if exists
            files_dir = os.path.join(proj_dir, 'files')
            if os.path.isdir(files_dir):
                dst_files = os.path.join(proj_backup, 'files')
                shutil.copytree(files_dir, dst_files, dirs_exist_ok=True)

    # Clean old backups (keep RETENTION_DAYS days)
    cutoff = now - timedelta(days=RETENTION_DAYS)
    removed = 0
    if os.path.exists(BACKUP_DIR):
        for d in os.listdir(BACKUP_DIR):
            dpath = os.path.join(BACKUP_DIR, d)
            if not os.path.isdir(dpath):
                continue
            try:
                d_date = datetime.strptime(d, '%Y-%m-%d').replace(tzinfo=TZ_HK)
                if d_date < cutoff:
                    shutil.rmtree(dpath)
                    removed += 1
            except ValueError:
                continue

    print(f"Backup completed: {date_str}")
    if removed:
        print(f"Removed {removed} old backup(s)")
    return date_str


def main():
    if '--list' in sys.argv:
        print("Available backups:")
        list_backups()
        return

    run_backup()


if __name__ == '__main__':
    main()
