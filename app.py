
from flask import (
    Flask, render_template, request,
    redirect, url_for, flash, session
)
from functools import wraps
from pathlib import Path
from datetime import date
import sqlite3
import os
import hmac

app = Flask(__name__)

app.secret_key = os.environ.get(
    "HOSPITAL_SECRET_KEY",
    "change-this-secret-before-deployment"
)

ADMIN_USERNAME = os.environ.get("HOSPITAL_ADMIN", "admin")
ADMIN_PASSWORD = os.environ.get("HOSPITAL_PASSWORD", "Admin@123")

DB_PATH = Path(__file__).with_name("hospital.db")

HOSPITAL_NAME = "MEDICARE HOSPITAL"
HOSPITAL_ADDRESS = "Main Road, Greater Noida, Uttar Pradesh"
HOSPITAL_PHONE = "7756895432"


# ---------------- DATABASE CONNECTION ----------------

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


# ---------------- DATABASE SETUP ----------------

def init_db():
    with get_db() as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                age INTEGER NOT NULL,
                gender TEXT NOT NULL,
                phone TEXT NOT NULL,
                problem TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                specialization TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                doctor_id INTEGER NOT NULL,
                appointment_date TEXT NOT NULL,
                FOREIGN KEY (patient_id)
                    REFERENCES patients(id) ON DELETE CASCADE,
                FOREIGN KEY (doctor_id)
                    REFERENCES doctors(id)
            );
        """)

        # Safely add the qualification column to an existing database.
        columns = {
            row["name"]
            for row in con.execute(
                "PRAGMA table_info(doctors)"
            ).fetchall()
        }

        if "qualification" not in columns:
            con.execute("""
                ALTER TABLE doctors
                ADD COLUMN qualification TEXT
                NOT NULL DEFAULT 'Not specified'
            """)

        # Demonstration data only. Verify actual qualifications
        # before using this system for a real hospital.
        doctors = [
            (
                "Dr. Amit Sharma",
                "General Physician",
                "MBBS (Demo)"
            ),
            (
                "Dr. Priya Verma",
                "Dentist",
                "BDS (Demo)"
            ),
            (
                "Dr. Rahul Singh",
                "Cardiologist",
                "MBBS, MD (Demo)"
            ),
            (
                "Dr. Neha Gupta",
                "Dermatologist",
                "MBBS, MD (Demo)"
            ),
            (
                "Dr. Arjun Mehta",
                "Orthopedic",
                "MBBS, MS (Demo)"
            ),
            (
                "Dr. Pooja Agarwal",
                "Pediatrician",
                "MBBS, MD (Demo)"
            ),
        ]

        for name, specialization, qualification in doctors:
            con.execute("""
                INSERT INTO doctors (name, specialization)
                SELECT ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM doctors
                    WHERE name = ? AND specialization = ?
                )
            """, (name, specialization, name, specialization))

            con.execute("""
                UPDATE doctors
                SET qualification = ?
                WHERE name = ? AND specialization = ?
                  AND (
                      qualification IS NULL
                      OR qualification = ''
                      OR qualification = 'Not specified'
                      OR qualification = 'MBBS (Demo)'
                      OR qualification = 'BDS (Demo)'
                      OR qualification = 'MBBS, MD (Demo)'
                      OR qualification = 'MBBS, MS (Demo)'
                  )
            """, (qualification, name, specialization))


# ---------------- LOGIN SECURITY ----------------

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


# ---------------- ADMIN LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin_logged_in"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        valid_user = hmac.compare_digest(
            username, ADMIN_USERNAME
        )
        valid_password = hmac.compare_digest(
            password, ADMIN_PASSWORD
        )

        if valid_user and valid_password:
            session.clear()
            session["admin_logged_in"] = True
            return redirect(url_for("index"))

        flash("Invalid username or password.")

    return render_template("login.html")


# ---------------- LOGOUT ----------------

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- DASHBOARD AND SEARCH ----------------

@app.route("/")
@login_required
def index():
    search = request.args.get("search", "").strip()

    with get_db() as con:
        if search:
            patients = con.execute("""
                SELECT * FROM patients
                WHERE name LIKE ? OR phone LIKE ?
                ORDER BY id DESC
            """, (f"%{search}%", f"%{search}%")).fetchall()
        else:
            patients = con.execute("""
                SELECT * FROM patients
                ORDER BY id DESC
            """).fetchall()

        doctors = con.execute("""
            SELECT * FROM doctors ORDER BY id
        """).fetchall()

        appointments = con.execute("""
            SELECT
                a.id,
                a.patient_id,
                a.doctor_id,
                a.appointment_date,
                p.name AS patient_name,
                d.name AS doctor_name,
                d.specialization,
                d.qualification
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN doctors d ON d.id = a.doctor_id
            ORDER BY a.appointment_date DESC, a.id DESC
        """).fetchall()

        patient_count = con.execute(
            "SELECT COUNT(*) FROM patients"
        ).fetchone()[0]

        doctor_count = con.execute(
            "SELECT COUNT(*) FROM doctors"
        ).fetchone()[0]

        appointment_count = con.execute(
            "SELECT COUNT(*) FROM appointments"
        ).fetchone()[0]

    return render_template(
        "index.html",
        patients=patients,
        doctors=doctors,
        appointments=appointments,
        patient_count=patient_count,
        doctor_count=doctor_count,
        appointment_count=appointment_count,
        search=search,
        today=date.today().isoformat()
    )


# ---------------- ADD PATIENT ----------------

@app.route("/add_patient", methods=["POST"])
@login_required
def add_patient():
    name = request.form.get("name", "").strip()
    age_text = request.form.get("age", "").strip()
    gender = request.form.get("gender", "").strip()
    phone = request.form.get("phone", "").strip()
    problem = request.form.get("problem", "").strip()

    if not all([name, age_text, gender, phone, problem]):
        flash("Please fill in all patient fields.")
        return redirect(url_for("index"))

    if len(name) > 100 or len(problem) > 300:
        flash("Name or problem description is too long.")
        return redirect(url_for("index"))

    try:
        age = int(age_text)
        if age < 0 or age > 120:
            raise ValueError
    except ValueError:
        flash("Age must be between 0 and 120.")
        return redirect(url_for("index"))

    if gender not in ("Male", "Female", "Other"):
        flash("Please select a valid gender.")
        return redirect(url_for("index"))

    if not phone.isdigit() or len(phone) != 10:
        flash("Enter a valid 10-digit phone number.")
        return redirect(url_for("index"))

    with get_db() as con:
        con.execute("""
            INSERT INTO patients
                (name, age, gender, phone, problem)
            VALUES (?, ?, ?, ?, ?)
        """, (name, age, gender, phone, problem))

    flash("Patient added successfully!")
    return redirect(url_for("index"))


# ---------------- BOOK APPOINTMENT ----------------

@app.route("/add_appointment", methods=["POST"])
@login_required
def add_appointment():
    patient_id = request.form.get("patient_id", type=int)
    doctor_id = request.form.get("doctor_id", type=int)
    appointment_date = request.form.get(
        "appointment_date", ""
    ).strip()

    try:
        chosen_date = date.fromisoformat(appointment_date)
        if chosen_date < date.today():
            raise ValueError
    except ValueError:
        flash("Select today or a future appointment date.")
        return redirect(url_for("index"))

    with get_db() as con:
        patient = con.execute(
            "SELECT id FROM patients WHERE id = ?",
            (patient_id,)
        ).fetchone() if patient_id else None

        doctor = con.execute(
            "SELECT id FROM doctors WHERE id = ?",
            (doctor_id,)
        ).fetchone() if doctor_id else None

        if not patient or not doctor:
            flash("Select a valid patient and doctor.")
            return redirect(url_for("index"))

        con.execute("""
            INSERT INTO appointments
                (patient_id, doctor_id, appointment_date)
            VALUES (?, ?, ?)
        """, (patient_id, doctor_id, appointment_date))

    flash("Appointment booked successfully!")
    return redirect(url_for("index"))


# ---------------- PRINT APPOINTMENT REPORT ----------------

@app.route("/print_appointment/<int:appointment_id>")
@login_required
def print_appointment(appointment_id):
    with get_db() as con:
        appointment = con.execute("""
            SELECT
                a.id AS appointment_id,
                a.appointment_date,
                p.name AS patient_name,
                p.age,
                p.gender,
                p.phone AS patient_phone,
                p.problem,
                d.name AS doctor_name,
                d.specialization,
                d.qualification
            FROM appointments a
            JOIN patients p ON p.id = a.patient_id
            JOIN doctors d ON d.id = a.doctor_id
            WHERE a.id = ?
        """, (appointment_id,)).fetchone()

    if not appointment:
        flash("Appointment report not found.")
        return redirect(url_for("index"))

    return render_template(
        "print_report.html",
        appointment=appointment,
        hospital_name=HOSPITAL_NAME,
        hospital_address=HOSPITAL_ADDRESS,
        hospital_phone=HOSPITAL_PHONE,
        report_date=date.today().strftime("%d-%m-%Y")
    )


# ---------------- DELETE PATIENT ----------------

@app.route("/delete_patient/<int:patient_id>", methods=["POST"])
@login_required
def delete_patient(patient_id):
    with get_db() as con:
        con.execute(
            "DELETE FROM patients WHERE id = ?",
            (patient_id,)
        )

    flash("Patient record deleted.")
    return redirect(url_for("index"))


# ---------------- START APPLICATION ----------------
init_db()

if __name__ == "__main__":
    app.run(debug=True)
