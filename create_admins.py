"""Initialize staff accounts and repair duplicate doctor/assistant records.

Run after importing schema.sql and applying the queue-assistant migration.
Safe to run repeatedly: it keeps one doctor record per normalized name+speciality
and one queue assistant account per doctor.
"""
import os
import mysql.connector
from werkzeug.security import generate_password_hash

CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "sijan123"),
    "database": os.getenv("DB_NAME", "queueless"),
}

def unique_phone(cur, preferred):
    phone = preferred
    suffix = 1
    while True:
        cur.execute("SELECT id FROM users WHERE phone=%s", (phone,))
        if not cur.fetchone():
            return phone
        phone = f"019{suffix:08d}"
        suffix += 1

conn = mysql.connector.connect(**CONFIG)
cur = conn.cursor(dictionary=True)
try:
    # Compatibility: add assistant assignment column if an older database lacks it.
    cur.execute("SHOW COLUMNS FROM users LIKE 'assigned_doctor_id'")
    if not cur.fetchone():
        cur.execute("ALTER TABLE users ADD COLUMN assigned_doctor_id INT NULL")
        conn.commit()
        print("Added users.assigned_doctor_id")

    # Find duplicate doctor records by case-insensitive trimmed name + speciality.
    cur.execute("""
        SELECT LOWER(TRIM(full_name)) AS n, LOWER(TRIM(speciality)) AS s,
               GROUP_CONCAT(id ORDER BY id) AS ids, COUNT(*) AS total
        FROM doctors
        GROUP BY LOWER(TRIM(full_name)), LOWER(TRIM(speciality))
        HAVING COUNT(*) > 1
    """)
    duplicate_groups = cur.fetchall()
    if duplicate_groups:
        # Temporarily move queue numbers out of the way so merged queues cannot
        # collide with the unique (doctor_id, visit_date, queue_number) index.
        cur.execute("UPDATE bookings SET queue_number=queue_number+1000000")
        for group in duplicate_groups:
            ids = [int(x) for x in group["ids"].split(",")]
            canonical = min(ids)
            duplicates = [x for x in ids if x != canonical]
            marks = ",".join(["%s"] * len(duplicates))
            cur.execute(f"UPDATE doctor_schedules SET doctor_id=%s WHERE doctor_id IN ({marks})",
                        (canonical, *duplicates))
            cur.execute(f"UPDATE bookings SET doctor_id=%s WHERE doctor_id IN ({marks})",
                        (canonical, *duplicates))
            cur.execute(f"UPDATE users SET assigned_doctor_id=%s WHERE assigned_doctor_id IN ({marks})",
                        (canonical, *duplicates))
            cur.execute(f"DELETE FROM doctors WHERE id IN ({marks})", tuple(duplicates))
            print(f"Merged duplicate doctor IDs {duplicates} into doctor ID {canonical}")

        # Remove duplicate schedule rows created by repeated schema imports.
        cur.execute("""
            SELECT doctor_id, day_of_week, start_time, end_time,
                   MIN(id) AS keep_id, COUNT(*) AS total
            FROM doctor_schedules
            GROUP BY doctor_id, day_of_week, start_time, end_time
            HAVING COUNT(*) > 1
        """)
        for row in cur.fetchall():
            cur.execute("""DELETE FROM doctor_schedules
                           WHERE doctor_id=%s AND day_of_week=%s
                             AND start_time=%s AND end_time=%s AND id<>%s""",
                        (row["doctor_id"], row["day_of_week"], row["start_time"],
                         row["end_time"], row["keep_id"]))

        # Re-number merged queues per doctor/date after moving queue numbers aside.
        cur.execute("""SELECT id, doctor_id, visit_date FROM bookings
                       ORDER BY doctor_id, visit_date, id""")
        booking_rows = cur.fetchall()
        counters = {}
        for booking in booking_rows:
            key = (booking["doctor_id"], booking["visit_date"])
            counters[key] = counters.get(key, 0) + 1
            cur.execute("UPDATE bookings SET queue_number=%s WHERE id=%s",
                        (counters[key], booking["id"]))
        conn.commit()
    else:
        print("No duplicate doctor records found.")

    # Ensure the two main administrator accounts exist.
    admin_accounts = [
        ("Queueless App Admin", "appadmin@queueless.local", "01700000001", "app_admin"),
        ("Hope Springs Hospital Admin", "hospitaladmin@queueless.local", "01700000002", "hospital_admin"),
    ]
    for name, email, phone, role in admin_accounts:
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            print(f"Already exists: {email}")
        else:
            phone = unique_phone(cur, phone)
            cur.execute("""INSERT INTO users
                (full_name,email,phone,password_hash,role)
                VALUES (%s,%s,%s,%s,%s)""",
                (name, email, phone, generate_password_hash("ChangeMe123!"), role))
            print(f"Created: {email} / ChangeMe123!")

    # Create exactly one assistant account for each active doctor.
    cur.execute("SELECT id, full_name FROM doctors WHERE is_active=1 ORDER BY id")
    doctors = cur.fetchall()
    for doctor in doctors:
        doctor_id = doctor["id"]
        email = f"assistant.{doctor_id}@hope-springs.local"
        cur.execute("""SELECT id,email FROM users
                       WHERE role='queue_manager' AND assigned_doctor_id=%s
                       ORDER BY CASE WHEN email=%s THEN 0 ELSE 1 END, id""",
                    (doctor_id, email))
        assistants = cur.fetchall()

        if assistants:
            keep_id = assistants[0]["id"]
            extra_ids = [a["id"] for a in assistants[1:]]
            if extra_ids:
                marks = ",".join(["%s"] * len(extra_ids))
                cur.execute(f"DELETE FROM users WHERE id IN ({marks})", tuple(extra_ids))
                print(f"Removed {len(extra_ids)} duplicate assistant account(s) for doctor ID {doctor_id}")
            cur.execute("""UPDATE users SET email=%s, full_name=%s,
                           assigned_doctor_id=%s, is_active=1 WHERE id=%s""",
                        (email, f"Assistant for {doctor['full_name']}", doctor_id, keep_id))
            print(f"Assistant ready: {email} / existing password retained")
        else:
            phone = unique_phone(cur, f"018{doctor_id:08d}")
            cur.execute("""INSERT INTO users
                (full_name,email,phone,password_hash,role,assigned_doctor_id)
                VALUES (%s,%s,%s,%s,'queue_manager',%s)""",
                (f"Assistant for {doctor['full_name']}", email, phone,
                 generate_password_hash("ChangeMe123!"), doctor_id))
            print(f"Created assistant: {email} / ChangeMe123!")

    conn.commit()
    print("\nSetup complete. Each active doctor now has one assistant account.")
    print("Default password for newly created accounts: ChangeMe123!")
    print("Existing assistant accounts keep their existing password.")
except Exception:
    conn.rollback()
    raise
finally:
    cur.close()
    conn.close()
