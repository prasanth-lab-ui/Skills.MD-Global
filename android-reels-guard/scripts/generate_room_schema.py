#!/usr/bin/env python3
"""
Generate a Room schema JSON stub for Reels Guard entities.
Usage: python3 generate_room_schema.py [--output schema.json]
"""

import json
import sys
import argparse

SCHEMA = {
    "formatVersion": 1,
    "database": {
        "name": "reels_guard_db",
        "version": 1,
        "entities": [
            {
                "tableName": "short_usage",
                "createSql": "CREATE TABLE IF NOT EXISTS short_usage (id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, packageName TEXT NOT NULL, dateEpochDay INTEGER NOT NULL, count INTEGER NOT NULL)",
                "fields": [
                    {"name": "id", "type": "INTEGER", "pk": True, "autoGen": True},
                    {"name": "packageName", "type": "TEXT"},
                    {"name": "dateEpochDay", "type": "INTEGER"},
                    {"name": "count", "type": "INTEGER"}
                ],
                "indices": [
                    {
                        "name": "index_short_usage_pkg_date",
                        "createSql": "CREATE INDEX IF NOT EXISTS index_short_usage_pkg_date ON short_usage (packageName, dateEpochDay)"
                    }
                ]
            },
            {
                "tableName": "app_rules",
                "createSql": "CREATE TABLE IF NOT EXISTS app_rules (packageName TEXT PRIMARY KEY NOT NULL, maxShortsPerDay INTEGER, blockedAfterHour INTEGER, fullBlock INTEGER NOT NULL, maxMinutesPerDay INTEGER)",
                "fields": [
                    {"name": "packageName", "type": "TEXT", "pk": True},
                    {"name": "maxShortsPerDay", "type": "INTEGER", "nullable": True},
                    {"name": "blockedAfterHour", "type": "INTEGER", "nullable": True},
                    {"name": "fullBlock", "type": "INTEGER"},
                    {"name": "maxMinutesPerDay", "type": "INTEGER", "nullable": True}
                ]
            }
        ]
    }
}

def main():
    parser = argparse.ArgumentParser(description="Generate Room schema JSON for Reels Guard")
    parser.add_argument("--output", "-o", default="reels_guard_schema.json", help="Output file path")
    args = parser.parse_args()

    with open(args.output, "w") as f:
        json.dump(SCHEMA, f, indent=2)

    print("Schema written to " + args.output)
    print("Tables: " + str(len(SCHEMA["database"]["entities"])))
    for e in SCHEMA["database"]["entities"]:
        print("  - " + e["tableName"] + " (" + str(len(e["fields"])) + " fields)")

if __name__ == "__main__":
    main()
