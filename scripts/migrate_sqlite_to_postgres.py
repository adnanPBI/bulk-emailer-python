import argparse

from migration import migrate_sqlite_to_postgres


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite DB into PostgreSQL (DATABASE_URL).")
    parser.add_argument("--sqlite-path", required=True, help="Path to legacy SQLite DB file (e.g. bulk_email.db)")
    parser.add_argument(
        "--truncate-target",
        action="store_true",
        help="TRUNCATE all Postgres tables before migrating (DESTRUCTIVE).",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="Delete the SQLite file after successful migration (DESTRUCTIVE).",
    )
    args = parser.parse_args()

    result = migrate_sqlite_to_postgres(
        args.sqlite_path,
        truncate_target=args.truncate_target,
        delete_source_sqlite=args.delete_source,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

