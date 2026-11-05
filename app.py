import os
from functools import wraps
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
from mysql.connector import Error
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key-before-deployment")

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "sijan123"),
    "database": os.getenv("DB_NAME", "queueless"),
}

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

def query_all(sql, params=()):
    conn = get_db()
    cur = conn.cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def query_one(sql, params=()):
    rows = query_all(sql, params)
    return rows[0] if rows else None

def execute(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    cur.close()
    conn.close()
    return last_id

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if session.get("role") not in roles:
                flash("You do not have permission to access that page.", "danger")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator

@app.context_processor
def inject_globals():
    return {"today": date.today().isoformat()}

@app.route("/")
def index():
    # One row per doctor. Joining schedules here created duplicate doctor cards.
    doctors = query_all("""
        SELECT d.id, d.full_name, d.speciality, d.qualification, d.bio, d.queue_status
        FROM doctors d
        WHERE d.is_active=1
          AND d.id IN (
            SELECT MIN(id) FROM doctors
            GROUP BY LOWER(TRIM(full_name)), LOWER(TRIM(speciality))
          )
        ORDER BY d.full_name
    """)
    return render_template("index.html", doctors=doctors)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        dob = request.form.get("date_of_birth") or None
        gender = request.form.get("gender") or None
        address = request.form.get("address", "").strip()
        if not full_name or not email or not phone or len(password) < 8:
            flash("Fill in all required fields. Password must be at least 8 characters.", "danger")
            return render_template("register.html")
        if query_one("SELECT id FROM users WHERE email=%s", (email,)):
            flash("An account with this email already exists.", "danger")
            return render_template("register.html")
        if query_one("SELECT id FROM users WHERE phone=%s", (phone,)):
            flash("An account with this phone number already exists.", "danger")
            return render_template("register.html")
        uid = execute("""INSERT INTO users
            (full_name,email,phone,password_hash,role,date_of_birth,gender,address)
            VALUES (%s,%s,%s,%s,'patient',%s,%s,%s)""",
            (full_name,email,phone,generate_password_hash(password),dob,gender,address))
        session.update(user_id=uid, name=full_name, role="patient")
        flash("Account created. Welcome to Queueless!", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = query_one("SELECT * FROM users WHERE email=%s AND is_active=1", (email,))
        selected_role = request.form.get("portal_role", "").strip()
        if user and selected_role and user["role"] != selected_role:
            flash("This account does not belong to the selected portal. Choose the correct portal and try again.", "danger")
            return render_template("login.html", selected_role=selected_role)
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session.update(user_id=user["id"], name=user["full_name"], role=user["role"])
            if user["role"] == "queue_manager":
                try:
                    assignment = query_one("SELECT assigned_doctor_id FROM users WHERE id=%s", (user["id"],))
                    session["assigned_doctor_id"] = assignment["assigned_doctor_id"] if assignment else None
                except Error:
                    session["assigned_doctor_id"] = None
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html", selected_role=request.form.get("portal_role", request.args.get("role", "")))

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))

@app.route("/dashboard")
@login_required
def dashboard():
    role = session["role"]
    if role == "patient":
        bookings = query_all("""SELECT b.*, d.full_name AS doctor_name, d.speciality
            FROM bookings b JOIN doctors d ON d.id=b.doctor_id
            WHERE b.patient_id=%s ORDER BY b.created_at DESC""", (session["user_id"],))
        return render_template("patient_dashboard.html", bookings=bookings)
    if role == "queue_manager":
        assigned_doctor = session.get("assigned_doctor_id")
        if not assigned_doctor:
            assigned = query_one("SELECT assigned_doctor_id FROM users WHERE id=%s", (session["user_id"],))
            assigned_doctor = assigned["assigned_doctor_id"] if assigned else None
        if assigned_doctor:
            bookings = query_all("""SELECT b.*, d.full_name AS doctor_name, d.speciality, u.full_name AS patient_name, u.phone
                FROM bookings b JOIN doctors d ON d.id=b.doctor_id JOIN users u ON u.id=b.patient_id
                WHERE b.visit_date=CURDATE() AND b.doctor_id=%s
                  AND b.status IN ('waiting','in_progress','paused')
                ORDER BY b.queue_number""", (assigned_doctor,))
            doctors = query_all("SELECT id,full_name,speciality,queue_status FROM doctors WHERE id=%s AND is_active=1", (assigned_doctor,))
        else:
            bookings, doctors = [], []
        return render_template("queue_dashboard.html", bookings=bookings, doctors=doctors)
    if role == "hospital_admin":
        doctors = query_all("SELECT * FROM doctors ORDER BY full_name")
        schedules = query_all("""SELECT s.*, d.full_name AS doctor_name, d.speciality
            FROM doctor_schedules s JOIN doctors d ON d.id=s.doctor_id
            ORDER BY d.full_name, s.day_of_week""")
        return render_template("hospital_dashboard.html", doctors=doctors, schedules=schedules)
    if role == "app_admin":
        users = query_all("SELECT id,full_name,email,phone,role,is_active,created_at FROM users ORDER BY created_at DESC")
        doctors = query_all("SELECT * FROM doctors ORDER BY full_name")
        counts = {
            "users": query_one("SELECT COUNT(*) AS n FROM users")["n"],
            "doctors": query_one("SELECT COUNT(*) AS n FROM doctors")["n"],
            "bookings": query_one("SELECT COUNT(*) AS n FROM bookings")["n"],
            "today": query_one("SELECT COUNT(*) AS n FROM bookings WHERE visit_date=CURDATE()")["n"],
        }
        return render_template("app_admin_dashboard.html", users=users, doctors=doctors, counts=counts)
    flash("Unknown account role.", "danger")
    return redirect(url_for("index"))

@app.route("/book", methods=["GET", "POST"])
@roles_required("patient")
def book():
    symptoms = query_all("SELECT * FROM symptoms ORDER BY category,label")
    doctors = query_all("SELECT * FROM doctors WHERE is_active=1 ORDER BY full_name")
    if request.method == "POST":
        doctor_id = request.form.get("doctor_id", type=int)
        visit_date = request.form.get("visit_date")
        symptom_ids = request.form.getlist("symptoms", type=int)
        notes = request.form.get("notes", "").strip()
        emergency = request.form.get("emergency") == "yes"
        if not visit_date or not symptom_ids:
            flash("Choose at least one symptom and a visit date.", "danger")
            return render_template("book.html", symptoms=symptoms, doctors=doctors)
        if visit_date < date.today().isoformat():
            flash("Visit date cannot be in the past.", "danger")
            return render_template("book.html", symptoms=symptoms, doctors=doctors)
        symptom_rows = query_all("SELECT id,label,recommended_speciality FROM symptoms WHERE id IN (" +
                                 ",".join(["%s"] * len(symptom_ids)) + ")", tuple(symptom_ids))
        if not symptom_rows:
            flash("Select at least one valid symptom.", "danger")
            return render_template("book.html", symptoms=symptoms, doctors=doctors)
        recommendations = sorted(set(s["recommended_speciality"] for s in symptom_rows if s["recommended_speciality"]))
        if not doctor_id and recommendations:
            suggested = query_one("SELECT id FROM doctors WHERE is_active=1 AND queue_status='open' AND speciality=%s ORDER BY id LIMIT 1", (recommendations[0],))
            doctor_id = suggested["id"] if suggested else None
        doctor = query_one("SELECT * FROM doctors WHERE id=%s AND is_active=1", (doctor_id,)) if doctor_id else None
        if not doctor:
            flash("No available doctor matched the selected speciality. Please choose another date or contact the hospital.", "danger")
            return render_template("book.html", symptoms=symptoms, doctors=doctors)
        if doctor["queue_status"] != "open":
            flash("This doctor's queue is currently closed or paused. Choose another doctor or try later.", "warning")
            return render_template("book.html", symptoms=symptoms, doctors=doctors)
        if emergency:
            flash("If this may be a medical emergency, do not wait for a queue. Contact emergency services or go to the nearest emergency department now.", "danger")
        if recommendations and doctor["speciality"] not in recommendations:
            flash("Based on the symptoms selected, the system suggests: " + ", ".join(recommendations) +
                  ". You can still proceed with your chosen doctor.", "warning")
        # Queue numbers are allocated per doctor and date. Production deployment should use a transaction/locking strategy.
        row = query_one("SELECT COALESCE(MAX(queue_number),0)+1 AS next_num FROM bookings WHERE doctor_id=%s AND visit_date=%s",
                        (doctor_id, visit_date))
        qnum = row["next_num"]
        booking_id = execute("""INSERT INTO bookings
            (patient_id,doctor_id,visit_date,queue_number,status,patient_notes,symptom_summary)
            VALUES (%s,%s,%s,%s,'waiting',%s,%s)""",
            (session["user_id"],doctor_id,visit_date,qnum,notes,", ".join(s["label"] for s in symptom_rows)))
        flash(f"Queue booked successfully. Your queue number is {qnum}. Booking ID: QL-{booking_id:05d}.", "success")
        return redirect(url_for("dashboard"))
    return render_template("book.html", symptoms=symptoms, doctors=doctors)

@app.route("/hospital/schedule", methods=["POST"])
@roles_required("hospital_admin", "app_admin")
def add_schedule():
    doctor_id = request.form.get("doctor_id", type=int)
    day = request.form.get("day_of_week", type=int)
    start = request.form.get("start_time")
    end = request.form.get("end_time")
    if not doctor_id or day is None or not start or not end or start >= end:
        flash("Enter a valid doctor, day, and time range.", "danger")
        return redirect(url_for("dashboard"))
    execute("""INSERT INTO doctor_schedules (doctor_id,day_of_week,start_time,end_time,is_active)
        VALUES (%s,%s,%s,%s,1)""", (doctor_id,day,start,end))
    flash("Doctor schedule added.", "success")
    return redirect(url_for("dashboard"))

@app.route("/hospital/schedule/<int:schedule_id>/toggle", methods=["POST"])
@roles_required("hospital_admin", "app_admin")
def toggle_schedule(schedule_id):
    row = query_one("SELECT is_active FROM doctor_schedules WHERE id=%s", (schedule_id,))
    if row:
        execute("UPDATE doctor_schedules SET is_active=%s WHERE id=%s", (0 if row["is_active"] else 1,schedule_id))
        flash("Schedule status updated.", "success")
    return redirect(url_for("dashboard"))

@app.route("/hospital/doctor", methods=["POST"])
@roles_required("hospital_admin", "app_admin")
def add_doctor():
    name = request.form.get("full_name", "").strip()
    speciality = request.form.get("speciality", "").strip()
    qualification = request.form.get("qualification", "").strip()
    bio = request.form.get("bio", "").strip()
    if not name or not speciality:
        flash("Doctor name and speciality are required.", "danger")
        return redirect(url_for("dashboard"))
    execute("INSERT INTO doctors (full_name,speciality,qualification,bio) VALUES (%s,%s,%s,%s)",
            (name,speciality,qualification,bio))
    flash("Doctor added. Add their schedule below.", "success")
    return redirect(url_for("dashboard"))

@app.route("/queue/doctor/<int:doctor_id>/status", methods=["POST"])
@roles_required("queue_manager", "app_admin")
def queue_status(doctor_id):
    if session.get("role") == "queue_manager":
        assigned = session.get("assigned_doctor_id")
        if not assigned or assigned != doctor_id:
            flash("You can only manage the queue assigned to your account.", "danger")
            return redirect(url_for("dashboard"))
    status = request.form.get("status")
    if status not in ("open","paused","closed"):
        flash("Invalid queue status.", "danger")
    else:
        execute("UPDATE doctors SET queue_status=%s WHERE id=%s", (status,doctor_id))
        flash("Queue status updated.", "success")
    return redirect(url_for("dashboard"))

@app.route("/queue/booking/<int:booking_id>/status", methods=["POST"])
@roles_required("queue_manager", "app_admin")
def booking_status(booking_id):
    if session.get("role") == "queue_manager":
        booking = query_one("SELECT doctor_id FROM bookings WHERE id=%s", (booking_id,))
        if not booking or booking["doctor_id"] != session.get("assigned_doctor_id"):
            flash("You can only update patients in your assigned doctor's queue.", "danger")
            return redirect(url_for("dashboard"))
    status = request.form.get("status")
    if status not in ("waiting","in_progress","completed","cancelled"):
        flash("Invalid booking status.", "danger")
    else:
        execute("UPDATE bookings SET status=%s WHERE id=%s", (status,booking_id))
        flash("Patient queue updated.", "success")
    return redirect(url_for("dashboard"))

@app.route("/admin/user/<int:user_id>/toggle", methods=["POST"])
@roles_required("app_admin")
def toggle_user(user_id):
    user = query_one("SELECT is_active,role FROM users WHERE id=%s", (user_id,))
    if user and user["role"] != "app_admin":
        execute("UPDATE users SET is_active=%s WHERE id=%s", (0 if user["is_active"] else 1,user_id))
        flash("User account status updated.", "success")
    else:
        flash("The primary app administrator cannot be disabled here.", "warning")
    return redirect(url_for("dashboard"))

@app.errorhandler(500)
def server_error(error):
    return render_template("error.html", message="A server error occurred. Check your database settings and terminal output."), 500

if __name__ == "__main__":
    app.run(debug=True)
