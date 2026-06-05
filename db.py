from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from state import BodyInfo, CommanderState


APP_DIR = Path.home() / ".local" / "share" / "observatory"
DB_PATH = APP_DIR / "observatory.sqlite"


def connect_db() -> sqlite3.Connection:
    APP_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS systems (
            system_address INTEGER PRIMARY KEY,
            system_name TEXT NOT NULL,
            first_seen TEXT,
            last_seen TEXT,
            body_count INTEGER,
            non_body_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS bodies (
            system_address INTEGER NOT NULL,
            body_id INTEGER NOT NULL,
            body_name TEXT NOT NULL,
            kind TEXT,
            subtype TEXT,
            distance_ls REAL,
            landable INTEGER,
            mapped INTEGER,
            scanned INTEGER,
            bio_signals INTEGER,
            geo_signals INTEGER,
            terraform_state TEXT,
            radius_m REAL,
            surface_temp_k REAL,
            last_seen TEXT,
            PRIMARY KEY (system_address, body_id),
            FOREIGN KEY (system_address) REFERENCES systems(system_address)
        );

        CREATE TABLE IF NOT EXISTS body_materials (
            system_address INTEGER NOT NULL,
            body_id INTEGER NOT NULL,
            material_name TEXT NOT NULL,
            percent REAL NOT NULL,
            PRIMARY KEY (system_address, body_id, material_name),
            FOREIGN KEY (system_address, body_id)
                REFERENCES bodies(system_address, body_id)
        );

        CREATE TABLE IF NOT EXISTS bio_expected (
            system_address INTEGER NOT NULL,
            body_id INTEGER NOT NULL,
            genus TEXT NOT NULL,
            PRIMARY KEY (system_address, body_id, genus),
            FOREIGN KEY (system_address, body_id)
                REFERENCES bodies(system_address, body_id)
        );

        CREATE TABLE IF NOT EXISTS bio_completed (
            system_address INTEGER NOT NULL,
            body_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            completed_at TEXT,
            PRIMARY KEY (system_address, body_id, name),
            FOREIGN KEY (system_address, body_id)
                REFERENCES bodies(system_address, body_id)
        );

        CREATE TABLE IF NOT EXISTS mining_signals (
            system_address INTEGER NOT NULL,
            body_name TEXT NOT NULL,
            signal_type TEXT NOT NULL,
            signal_localised TEXT,
            count INTEGER,
            last_seen TEXT,
            PRIMARY KEY (system_address, body_name, signal_type)
        );

        CREATE TABLE IF NOT EXISTS rings (
            system_address INTEGER NOT NULL,
            body_id INTEGER NOT NULL,
            ring_name TEXT NOT NULL,
            ring_class TEXT,
            mass_mt REAL,
            inner_rad REAL,
            outer_rad REAL,
            PRIMARY KEY (system_address, body_id, ring_name),
            FOREIGN KEY (system_address, body_id)
                REFERENCES bodies(system_address, body_id)
        );

        CREATE TABLE IF NOT EXISTS first_footfalls (
            system_address INTEGER NOT NULL,
            body_id INTEGER NOT NULL,
            system_name TEXT,
            body_name TEXT,
            first_seen TEXT,
            latitude REAL,
            longitude REAL,
            PRIMARY KEY (system_address, body_id)
        );
        """
    )
    conn.commit()


def bool_to_int(value: Optional[bool]) -> Optional[int]:
    if value is None:
        return None
    return 1 if value else 0


def upsert_current_system(conn: sqlite3.Connection, state: CommanderState) -> None:
    if state.system_address is None or not state.system:
        return

    conn.execute(
        """
        INSERT INTO systems (
            system_address,
            system_name,
            first_seen,
            last_seen,
            body_count,
            non_body_count
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address) DO UPDATE SET
            system_name = excluded.system_name,
            last_seen = excluded.last_seen,
            body_count = excluded.body_count,
            non_body_count = excluded.non_body_count
        """,
        (
            state.system_address,
            state.system,
            state.last_timestamp,
            state.last_timestamp,
            state.body_count,
            state.non_body_count,
        ),
    )


def upsert_body(conn: sqlite3.Connection, state: CommanderState, body: BodyInfo) -> None:
    if state.system_address is None:
        return

    if body.body_id is None:
        return

    upsert_current_system(conn, state)

    conn.execute(
        """
        INSERT INTO bodies (
            system_address,
            body_id,
            body_name,
            kind,
            subtype,
            distance_ls,
            landable,
            mapped,
            scanned,
            bio_signals,
            geo_signals,
            terraform_state,
            radius_m,
            surface_temp_k,
            last_seen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address, body_id) DO UPDATE SET
            body_name = excluded.body_name,
            kind = excluded.kind,
            subtype = excluded.subtype,
            distance_ls = excluded.distance_ls,
            landable = excluded.landable,
            mapped = excluded.mapped,
            scanned = excluded.scanned,
            bio_signals = excluded.bio_signals,
            geo_signals = excluded.geo_signals,
            terraform_state = excluded.terraform_state,
            radius_m = excluded.radius_m,
            surface_temp_k = excluded.surface_temp_k,
            last_seen = excluded.last_seen
        """,
        (
            state.system_address,
            body.body_id,
            body.name,
            body.kind,
            body.subtype,
            body.distance_ls,
            bool_to_int(body.landable),
            bool_to_int(body.mapped),
            bool_to_int(body.scanned),
            body.bio_signals,
            body.geo_signals,
            body.terraform_state,
            body.radius_m,
            body.surface_temp_k,
            state.last_timestamp,
        ),
    )

    for mat_name, percent in body.materials.items():
        conn.execute(
            """
            INSERT INTO body_materials (
                system_address,
                body_id,
                material_name,
                percent
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(system_address, body_id, material_name)
            DO UPDATE SET percent = excluded.percent
            """,
            (
                state.system_address,
                body.body_id,
                mat_name.lower(),
                percent,
            ),
        )

    for genus in body.bio_expected_genuses:
        conn.execute(
            """
            INSERT OR IGNORE INTO bio_expected (
                system_address,
                body_id,
                genus
            )
            VALUES (?, ?, ?)
            """,
            (
                state.system_address,
                body.body_id,
                genus,
            ),
        )

    for name in body.bio_completed_species:
        conn.execute(
            """
            INSERT INTO bio_completed (
                system_address,
                body_id,
                name,
                completed_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(system_address, body_id, name)
            DO UPDATE SET completed_at = excluded.completed_at
            """,
            (
                state.system_address,
                body.body_id,
                name,
                state.last_timestamp,
            ),
        )

    for ring in body.rings:
        ring_name = ring.get("Name")
        if not ring_name:
            continue

        conn.execute(
            """
            INSERT INTO rings (
                system_address,
                body_id,
                ring_name,
                ring_class,
                mass_mt,
                inner_rad,
                outer_rad
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id, ring_name)
            DO UPDATE SET
                ring_class = excluded.ring_class,
                mass_mt = excluded.mass_mt,
                inner_rad = excluded.inner_rad,
                outer_rad = excluded.outer_rad
            """,
            (
                state.system_address,
                body.body_id,
                ring_name,
                ring.get("RingClass"),
                ring.get("MassMT"),
                ring.get("InnerRad"),
                ring.get("OuterRad"),
            ),
        )


def upsert_mining_signals(conn: sqlite3.Connection, state: CommanderState, body: BodyInfo) -> None:
    if state.system_address is None:
        return

    if not body.mining_signals:
        return

    upsert_current_system(conn, state)

    for signal in body.mining_signals:
        signal_type = signal.get("type")
        if not signal_type:
            continue

        conn.execute(
            """
            INSERT INTO mining_signals (
                system_address,
                body_name,
                signal_type,
                signal_localised,
                count,
                last_seen
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_name, signal_type)
            DO UPDATE SET
                signal_localised = excluded.signal_localised,
                count = excluded.count,
                last_seen = excluded.last_seen
            """,
            (
                state.system_address,
                body.name,
                signal_type,
                signal.get("localised"),
                signal.get("count"),
                state.last_timestamp,
            ),
        )


def save_state_snapshot(conn: sqlite3.Connection, state: CommanderState) -> None:
    upsert_current_system(conn, state)

    for body in state.bodies.values():
        upsert_body(conn, state, body)
        upsert_mining_signals(conn, state, body)

    conn.commit()

def incomplete_bio_bodies(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            s.system_name,
            s.system_address,
            b.body_name,
            b.body_id,
            b.bio_signals,
            GROUP_CONCAT(DISTINCT e.genus) AS expected,
            GROUP_CONCAT(DISTINCT c.name) AS completed
        FROM bodies b
        JOIN systems s
            ON s.system_address = b.system_address
        LEFT JOIN bio_expected e
            ON e.system_address = b.system_address
            AND e.body_id = b.body_id
        LEFT JOIN bio_completed c
            ON c.system_address = b.system_address
            AND c.body_id = b.body_id
        WHERE b.bio_signals IS NOT NULL
          AND b.bio_signals > 0
        GROUP BY
            s.system_name,
            s.system_address,
            b.body_name,
            b.body_id,
            b.bio_signals
        HAVING
            completed IS NULL
            OR expected IS NULL
            OR completed != expected
        ORDER BY s.last_seen DESC
        """
    ).fetchall()

def save_first_footfall(conn: sqlite3.Connection, state: CommanderState, event: dict) -> None:
    if state.system_address is None:
        return

    body_id = event.get("BodyID")
    if body_id is None:
        return

    body_name = event.get("Body") or state.body
    if not body_name:
        body_name = "Unknown body"

    conn.execute(
        """
        INSERT INTO first_footfalls (
            system_address,
            body_id,
            system_name,
            body_name,
            first_seen,
            latitude,
            longitude
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(system_address, body_id)
        DO UPDATE SET
            system_name = excluded.system_name,
            body_name = excluded.body_name,
            first_seen = excluded.first_seen,
            latitude = excluded.latitude,
            longitude = excluded.longitude
        """,
        (
            state.system_address,
            body_id,
            state.system,
            body_name,
            event.get("timestamp") or state.last_timestamp,
            event.get("Latitude"),
            event.get("Longitude"),
        ),
    )

    conn.commit()
