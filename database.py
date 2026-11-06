import os
import sqlite3
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from werkzeug.security import generate_password_hash

DB_NAME = os.getenv("DATABASE_PATH", "hr_system.db")


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ensure_payroll_tables():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employee_salary_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL UNIQUE,
                basic_salary REAL NOT NULL DEFAULT 0,
                working_days_per_month INTEGER NOT NULL DEFAULT 26,
                work_hours_per_day REAL NOT NULL DEFAULT 8,
                work_hours_per_week REAL NOT NULL DEFAULT 48,
                official_work_days TEXT NOT NULL DEFAULT 'Sun-Thu',
                start_time TEXT NOT NULL DEFAULT '08:00',
                end_time TEXT NOT NULL DEFAULT '17:00',
                grace_period_minutes INTEGER NOT NULL DEFAULT 10,
                regular_hour_value REAL NOT NULL DEFAULT 0,
                late_hour_value REAL NOT NULL DEFAULT 0,
                overtime_multiplier REAL NOT NULL DEFAULT 1.5,
                friday_overtime_multiplier REAL NOT NULL DEFAULT 2.0,
                holiday_overtime_multiplier REAL NOT NULL DEFAULT 2.5,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS overtime_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                employee_number TEXT,
                department TEXT,
                work_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                total_hours REAL NOT NULL DEFAULT 0,
                reason TEXT,
                requested_by TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                approved_by TEXT,
                approved_at TEXT,
                payroll_month TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS friday_overtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                employee_number TEXT,
                department TEXT,
                friday_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                total_hours REAL NOT NULL DEFAULT 0,
                regular_hour_value REAL NOT NULL DEFAULT 0,
                multiplier REAL NOT NULL DEFAULT 2.0,
                total_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                approved_by TEXT,
                approved_at TEXT,
                payroll_month TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS holiday_overtime (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                holiday_name TEXT NOT NULL,
                work_date TEXT NOT NULL,
                total_hours REAL NOT NULL DEFAULT 0,
                multiplier REAL NOT NULL DEFAULT 2.5,
                total_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                approved_by TEXT,
                approved_at TEXT,
                payroll_month TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                period_month TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'draft',
                created_by TEXT,
                approved_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                period_month TEXT NOT NULL,
                basic_salary REAL NOT NULL DEFAULT 0,
                late_minutes INTEGER NOT NULL DEFAULT 0,
                late_deduction REAL NOT NULL DEFAULT 0,
                regular_overtime REAL NOT NULL DEFAULT 0,
                friday_overtime REAL NOT NULL DEFAULT 0,
                holiday_overtime REAL NOT NULL DEFAULT 0,
                other_allowances REAL NOT NULL DEFAULT 0,
                total_deductions REAL NOT NULL DEFAULT 0,
                net_salary REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                approved_by TEXT,
                approved_at TEXT,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(employee_id, period_month),
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                employee_id INTEGER,
                action TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                comments TEXT,
                approver TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                period_month TEXT NOT NULL,
                adjustment_type TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                reason TEXT,
                created_by TEXT,
                approved_by TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                module TEXT NOT NULL,
                employee_id INTEGER,
                user_name TEXT,
                old_value TEXT,
                new_value TEXT,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def ensure_employee_salary_defaults():
    with get_connection() as conn:
        employees = conn.execute("SELECT id, full_name, base_salary FROM employees").fetchall()
        for employee in employees:
            existing = conn.execute("SELECT id FROM employee_salary_settings WHERE employee_id = ?", (employee["id"],)).fetchone()
            if not existing:
                hourly_rate = Decimal(str(float(employee["base_salary"] or 0) / 208)) if employee["base_salary"] else Decimal("0")
                conn.execute(
                    """
                    INSERT INTO employee_salary_settings (
                        employee_id, basic_salary, working_days_per_month, work_hours_per_day, work_hours_per_week,
                        official_work_days, start_time, end_time, grace_period_minutes, regular_hour_value,
                        late_hour_value, overtime_multiplier, friday_overtime_multiplier, holiday_overtime_multiplier
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        employee["id"],
                        float(employee["base_salary"] or 0),
                        26,
                        8,
                        48,
                        "Sun-Thu",
                        "08:00",
                        "17:00",
                        10,
                        float(hourly_rate),
                        float(hourly_rate),
                        1.5,
                        2.0,
                        2.5,
                    ),
                )
        conn.commit()


def get_salary_settings(employee_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM employee_salary_settings WHERE employee_id = ?", (employee_id,)).fetchone()
        if row:
            return dict(row)

        employee = conn.execute("SELECT id, base_salary, work_hours, check_in_time, check_out_time FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if not employee:
            return {
                "basic_salary": 0,
                "working_days_per_month": 26,
                "work_hours_per_day": 8,
                "work_hours_per_week": 48,
                "official_work_days": "Sun-Thu",
                "start_time": "08:00",
                "end_time": "17:00",
                "grace_period_minutes": 10,
                "regular_hour_value": 0,
                "late_hour_value": 0,
                "overtime_multiplier": 1.5,
                "friday_overtime_multiplier": 2.0,
                "holiday_overtime_multiplier": 2.5,
            }

        hour_rate = Decimal(str(float(employee["base_salary"] or 0) / 208)) if employee["base_salary"] else Decimal("0")
        settings = {
            "employee_id": employee["id"],
            "basic_salary": float(employee["base_salary"] or 0),
            "working_days_per_month": 26,
            "work_hours_per_day": float(employee["work_hours"] or 8),
            "work_hours_per_week": 48,
            "official_work_days": "Sun-Thu",
            "start_time": employee["check_in_time"] or "08:00",
            "end_time": employee["check_out_time"] or "17:00",
            "grace_period_minutes": 10,
            "regular_hour_value": float(hour_rate),
            "late_hour_value": float(hour_rate),
            "overtime_multiplier": 1.5,
            "friday_overtime_multiplier": 2.0,
            "holiday_overtime_multiplier": 2.5,
        }
        conn.execute(
            """
            INSERT INTO employee_salary_settings (
                employee_id, basic_salary, working_days_per_month, work_hours_per_day, work_hours_per_week,
                official_work_days, start_time, end_time, grace_period_minutes, regular_hour_value,
                late_hour_value, overtime_multiplier, friday_overtime_multiplier, holiday_overtime_multiplier
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                settings["employee_id"],
                settings["basic_salary"],
                settings["working_days_per_month"],
                settings["work_hours_per_day"],
                settings["work_hours_per_week"],
                settings["official_work_days"],
                settings["start_time"],
                settings["end_time"],
                settings["grace_period_minutes"],
                settings["regular_hour_value"],
                settings["late_hour_value"],
                settings["overtime_multiplier"],
                settings["friday_overtime_multiplier"],
                settings["holiday_overtime_multiplier"],
            ),
        )
        conn.commit()
        return settings


def calculate_hourly_rate(basic_salary, working_days_per_month=26, work_hours_per_day=8):
    if not basic_salary or not working_days_per_month or not work_hours_per_day:
        return Decimal("0")
    total_hours = Decimal(str(working_days_per_month)) * Decimal(str(work_hours_per_day))
    return money(Decimal(str(basic_salary)) / total_hours)


def calculate_late_minutes(actual_time, start_time, grace_period_minutes=0):
    if not actual_time or not start_time:
        return 0
    try:
        actual = datetime.strptime(actual_time, "%H:%M")
        start = datetime.strptime(start_time, "%H:%M")
    except ValueError:
        try:
            actual = datetime.strptime(actual_time, "%Y-%m-%d %H:%M")
            start = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
        except ValueError:
            return 0
    delta_minutes = int((actual - start).total_seconds() // 60)
    return max(0, delta_minutes - int(grace_period_minutes))


def get_employee_late_summary(employee_id, period_month):
    with get_connection() as conn:
        settings = get_salary_settings(employee_id)
        rows = conn.execute(
            "SELECT date, status, check_in_time FROM attendance_records WHERE employee_id = ? AND strftime('%Y-%m', date) = ? ORDER BY date ASC",
            (employee_id, period_month),
        ).fetchall()

        total_minutes = 0
        total_deduction = Decimal("0")
        late_count = 0
        for row in rows:
            if row["status"] != "late":
                continue
            if not row["check_in_time"]:
                continue
            minutes = calculate_late_minutes(row["check_in_time"], settings.get("start_time", "08:00"), settings.get("grace_period_minutes", 0))
            if minutes <= 0:
                continue
            total_minutes += minutes
            late_count += 1
            late_hour_value = Decimal(str(settings.get("late_hour_value") or settings.get("regular_hour_value") or 0))
            total_deduction += (Decimal(minutes) / Decimal(60)) * late_hour_value

        return {
            "late_minutes": total_minutes,
            "late_count": late_count,
            "total_deduction": float(money(total_deduction)),
        }


def add_overtime_request(employee_id, work_date, start_time, end_time, reason, requested_by="HR", payroll_month=None):
    employee = get_employee_by_id(employee_id)
    if not employee:
        return None
    hours = 0
    try:
        start = datetime.strptime(work_date + " " + start_time, "%Y-%m-%d %H:%M")
        end = datetime.strptime(work_date + " " + end_time, "%Y-%m-%d %H:%M")
        hours = round((end - start).total_seconds() / 3600, 2)
    except ValueError:
        return None

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO overtime_requests (employee_id, employee_number, department, work_date, start_time, end_time, total_hours, reason, requested_by, payroll_month)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (employee_id, employee.get("employee_number") or "", employee.get("department") or "", work_date, start_time, end_time, hours, reason, requested_by, payroll_month or work_date[:7]),
        )
        conn.commit()
        return cursor.lastrowid


def get_overtime_requests(status=None):
    with get_connection() as conn:
        query = "SELECT ot.*, e.full_name, e.role, e.department FROM overtime_requests ot JOIN employees e ON e.id = ot.employee_id"
        params = []
        if status and status != "all":
            query += " WHERE ot.status = ?"
            params.append(status)
        query += " ORDER BY ot.work_date DESC, ot.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def update_overtime_status(record_id, status, approved_by="admin"):
    with get_connection() as conn:
        conn.execute(
            "UPDATE overtime_requests SET status = ?, approved_by = ?, approved_at = ? WHERE id = ?",
            (status, approved_by, datetime.today().strftime("%Y-%m-%d %H:%M:%S"), record_id),
        )
        conn.commit()


def add_friday_overtime(employee_id, friday_date, start_time, end_time, requested_by="HR"):
    employee = get_employee_by_id(employee_id)
    if not employee:
        return None
    settings = get_salary_settings(employee_id)
    try:
        start = datetime.strptime(friday_date + " " + start_time, "%Y-%m-%d %H:%M")
        end = datetime.strptime(friday_date + " " + end_time, "%Y-%m-%d %H:%M")
        hours = round((end - start).total_seconds() / 3600, 2)
    except ValueError:
        return None

    hour_value = Decimal(str(settings.get("regular_hour_value") or 0))
    multiplier = Decimal(str(settings.get("friday_overtime_multiplier") or 2.0))
    total_amount = money((Decimal(str(hours)) * hour_value * multiplier))

    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO friday_overtime (employee_id, employee_number, department, friday_date, start_time, end_time, total_hours, regular_hour_value, multiplier, total_amount, payroll_month, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                employee_id,
                employee.get("employee_number") or "",
                employee.get("department") or "",
                friday_date,
                start_time,
                end_time,
                hours,
                settings.get("regular_hour_value") or 0,
                settings.get("friday_overtime_multiplier") or 2.0,
                float(total_amount),
                friday_date[:7],
            ),
        )
        conn.commit()
        return cursor.lastrowid


def get_friday_overtime(status=None):
    with get_connection() as conn:
        query = "SELECT fo.*, e.full_name, e.role FROM friday_overtime fo JOIN employees e ON e.id = fo.employee_id"
        params = []
        if status and status != "all":
            query += " WHERE fo.status = ?"
            params.append(status)
        query += " ORDER BY fo.friday_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def add_holiday_overtime(employee_id, holiday_name, work_date, total_hours, multiplier, approved_by="admin"):
    employee = get_employee_by_id(employee_id)
    if not employee:
        return None
    settings = get_salary_settings(employee_id)
    amount = money((Decimal(str(total_hours)) * Decimal(str(settings.get("regular_hour_value") or 0)) * Decimal(str(multiplier))))
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO holiday_overtime (employee_id, holiday_name, work_date, total_hours, multiplier, total_amount, payroll_month, status, approved_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (employee_id, holiday_name, work_date, total_hours, multiplier, float(amount), work_date[:7], approved_by),
        )
        conn.commit()
        return cursor.lastrowid


def get_holiday_overtime(status=None):
    with get_connection() as conn:
        query = "SELECT ho.*, e.full_name, e.role FROM holiday_overtime ho JOIN employees e ON e.id = ho.employee_id"
        params = []
        if status and status != "all":
            query += " WHERE ho.status = ?"
            params.append(status)
        query += " ORDER BY ho.work_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def upsert_payroll_period(period_month, created_by="system"):
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM payroll_periods WHERE period_month = ?", (period_month,)).fetchone()
        if existing:
            return existing["id"]
        cursor = conn.execute(
            "INSERT INTO payroll_periods (period_month, status, created_by, created_at) VALUES (?, 'draft', ?, ?)",
            (period_month, created_by, datetime.today().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        return cursor.lastrowid


def generate_employee_payroll_record(employee_id, period_month):
    employee = get_employee_by_id(employee_id)
    if not employee:
        return None
    settings = get_salary_settings(employee_id)
    basic_salary = Decimal(str(employee.get("base_salary") or 0))
    regular_rate = Decimal(str(settings.get("regular_hour_value") or 0))
    late_summary = get_employee_late_summary(employee_id, period_month)
    late_deduction = Decimal(str(late_summary["total_deduction"]))
    regular_overtime_total = Decimal("0")
    friday_total = Decimal("0")
    holiday_total = Decimal("0")

    with get_connection() as conn:
        approved_overtime = conn.execute(
            "SELECT COALESCE(SUM(total_hours), 0) AS hours FROM overtime_requests WHERE employee_id = ? AND payroll_month = ? AND status = 'approved'",
            (employee_id, period_month),
        ).fetchone()
        if approved_overtime:
            regular_overtime_total = (Decimal(str(approved_overtime["hours"])) * regular_rate * Decimal(str(settings.get("overtime_multiplier") or 1.5)))

        approved_friday = conn.execute(
            "SELECT COALESCE(SUM(total_amount), 0) AS total FROM friday_overtime WHERE employee_id = ? AND payroll_month = ? AND status = 'approved'",
            (employee_id, period_month),
        ).fetchone()
        if approved_friday:
            friday_total = Decimal(str(approved_friday["total"]))

        approved_holiday = conn.execute(
            "SELECT COALESCE(SUM(total_amount), 0) AS total FROM holiday_overtime WHERE employee_id = ? AND payroll_month = ? AND status = 'approved'",
            (employee_id, period_month),
        ).fetchone()
        if approved_holiday:
            holiday_total = Decimal(str(approved_holiday["total"]))

    total_allowances = regular_overtime_total + friday_total + holiday_total
    total_deductions = late_deduction
    net_salary = basic_salary + total_allowances - total_deductions
    payroll_record = {
        "employee_id": employee_id,
        "period_month": period_month,
        "basic_salary": float(basic_salary),
        "late_minutes": late_summary["late_minutes"],
        "late_deduction": float(money(late_deduction)),
        "regular_overtime": float(money(regular_overtime_total)),
        "friday_overtime": float(money(friday_total)),
        "holiday_overtime": float(money(holiday_total)),
        "other_allowances": 0.0,
        "total_deductions": float(money(total_deductions)),
        "net_salary": float(money(net_salary)),
        "status": "draft",
    }

    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM payroll_records WHERE employee_id = ? AND period_month = ?", (employee_id, period_month)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE payroll_records SET basic_salary = ?, late_minutes = ?, late_deduction = ?, regular_overtime = ?, friday_overtime = ?, holiday_overtime = ?, other_allowances = ?, total_deductions = ?, net_salary = ?, status = ?
                WHERE employee_id = ? AND period_month = ?
                """,
                (
                    payroll_record["basic_salary"],
                    payroll_record["late_minutes"],
                    payroll_record["late_deduction"],
                    payroll_record["regular_overtime"],
                    payroll_record["friday_overtime"],
                    payroll_record["holiday_overtime"],
                    payroll_record["other_allowances"],
                    payroll_record["total_deductions"],
                    payroll_record["net_salary"],
                    payroll_record["status"],
                    employee_id,
                    period_month,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO payroll_records (employee_id, period_month, basic_salary, late_minutes, late_deduction, regular_overtime, friday_overtime, holiday_overtime, other_allowances, total_deductions, net_salary, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    period_month,
                    payroll_record["basic_salary"],
                    payroll_record["late_minutes"],
                    payroll_record["late_deduction"],
                    payroll_record["regular_overtime"],
                    payroll_record["friday_overtime"],
                    payroll_record["holiday_overtime"],
                    payroll_record["other_allowances"],
                    payroll_record["total_deductions"],
                    payroll_record["net_salary"],
                    payroll_record["status"],
                ),
            )
        conn.commit()

    return payroll_record


def generate_monthly_payroll(period_month, created_by="system"):
    upsert_payroll_period(period_month, created_by)
    employees = get_employees(status="all")
    created = []
    for employee in employees:
        created.append(generate_employee_payroll_record(employee["id"], period_month))
    return created


def get_payroll_records(period_month=None):
    with get_connection() as conn:
        query = "SELECT pr.*, e.full_name, e.role, e.department FROM payroll_records pr JOIN employees e ON e.id = pr.employee_id"
        params = []
        if period_month:
            query += " WHERE pr.period_month = ?"
            params.append(period_month)
        query += " ORDER BY pr.period_month DESC, e.full_name ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def update_payroll_record_status(employee_id, period_month, status, approved_by="admin"):
    with get_connection() as conn:
        conn.execute(
            "UPDATE payroll_records SET status = ?, approved_by = ?, approved_at = ? WHERE employee_id = ? AND period_month = ?",
            (status, approved_by, datetime.today().strftime("%Y-%m-%d %H:%M:%S"), employee_id, period_month),
        )
        conn.commit()


def add_payroll_audit_log(action, module, employee_id=None, user_name="system", old_value="", new_value="", reason=""):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO payroll_audit_logs (action, module, employee_id, user_name, old_value, new_value, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (action, module, employee_id, user_name, str(old_value), str(new_value), reason),
        )
        conn.commit()


def save_salary_settings(employee_id, payload, user_name="system"):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM employee_salary_settings WHERE employee_id = ?", (employee_id,)).fetchone()
        old_values = dict(row) if row else {}
        conn.execute(
            """
            INSERT INTO employee_salary_settings (
                employee_id, basic_salary, working_days_per_month, work_hours_per_day, work_hours_per_week,
                official_work_days, start_time, end_time, grace_period_minutes, regular_hour_value,
                late_hour_value, overtime_multiplier, friday_overtime_multiplier, holiday_overtime_multiplier, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(employee_id) DO UPDATE SET
                basic_salary = excluded.basic_salary,
                working_days_per_month = excluded.working_days_per_month,
                work_hours_per_day = excluded.work_hours_per_day,
                work_hours_per_week = excluded.work_hours_per_week,
                official_work_days = excluded.official_work_days,
                start_time = excluded.start_time,
                end_time = excluded.end_time,
                grace_period_minutes = excluded.grace_period_minutes,
                regular_hour_value = excluded.regular_hour_value,
                late_hour_value = excluded.late_hour_value,
                overtime_multiplier = excluded.overtime_multiplier,
                friday_overtime_multiplier = excluded.friday_overtime_multiplier,
                holiday_overtime_multiplier = excluded.holiday_overtime_multiplier,
                updated_at = excluded.updated_at
            """,
            (
                employee_id,
                float(payload.get("basic_salary") or 0),
                int(payload.get("working_days_per_month") or 26),
                float(payload.get("work_hours_per_day") or 8),
                float(payload.get("work_hours_per_week") or 48),
                payload.get("official_work_days") or "Sun-Thu",
                payload.get("start_time") or "08:00",
                payload.get("end_time") or "17:00",
                int(payload.get("grace_period_minutes") or 10),
                float(payload.get("regular_hour_value") or 0),
                float(payload.get("late_hour_value") or 0),
                float(payload.get("overtime_multiplier") or 1.5),
                float(payload.get("friday_overtime_multiplier") or 2.0),
                float(payload.get("holiday_overtime_multiplier") or 2.5),
                datetime.today().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        add_payroll_audit_log("update_salary_settings", "payroll", employee_id, user_name, str(old_values), str(payload), "Updated payroll settings")
        return True




def get_connection():
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor

            conn = psycopg2.connect(database_url)
            conn.cursor_factory = RealDictCursor
            return conn
        except Exception:
            pass

        try:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(database_url)
            return conn
        except Exception:
            pass

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_employee_columns():
    with get_connection() as conn:
        columns = conn.execute("PRAGMA table_info(employees)").fetchall()
        existing = {row[1] for row in columns}

        if "employee_number" not in existing:
            conn.execute("ALTER TABLE employees ADD COLUMN employee_number TEXT")
        if "department" not in existing:
            conn.execute("ALTER TABLE employees ADD COLUMN department TEXT")
        if "status" not in existing:
            conn.execute("ALTER TABLE employees ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if "employment_type" not in existing:
            conn.execute("ALTER TABLE employees ADD COLUMN employment_type TEXT NOT NULL DEFAULT 'full_time'")
        if "notes" not in existing:
            conn.execute("ALTER TABLE employees ADD COLUMN notes TEXT")
        if "check_in_time" not in existing:
            conn.execute("ALTER TABLE employees ADD COLUMN check_in_time TEXT NOT NULL DEFAULT '08:00'")
        if "check_out_time" not in existing:
            conn.execute("ALTER TABLE employees ADD COLUMN check_out_time TEXT NOT NULL DEFAULT '17:00'")


def ensure_attendance_columns():
    with get_connection() as conn:
        columns = conn.execute("PRAGMA table_info(attendance_records)").fetchall()
        existing = {row[1] for row in columns}

        if "check_in_time" not in existing:
            conn.execute("ALTER TABLE attendance_records ADD COLUMN check_in_time TEXT")
        if "check_out_time" not in existing:
            conn.execute("ALTER TABLE attendance_records ADD COLUMN check_out_time TEXT")


def ensure_user_columns():
    with get_connection() as conn:
        columns = conn.execute("PRAGMA table_info(users)").fetchall() if isinstance(conn, sqlite3.Connection) else []
        if isinstance(conn, sqlite3.Connection):
            existing = {row[1] for row in columns}
            if "role" not in existing:
                conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'employee'")


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'employee'
            )
            """
        )

        if isinstance(conn, sqlite3.Connection):
            ensure_user_columns()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                phone TEXT,
                employee_number TEXT,
                department TEXT,
                base_salary REAL NOT NULL DEFAULT 0,
                work_hours REAL NOT NULL DEFAULT 0,
                hire_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                employment_type TEXT NOT NULL DEFAULT 'full_time',
                notes TEXT,
                check_in_time TEXT NOT NULL DEFAULT '08:00',
                check_out_time TEXT NOT NULL DEFAULT '17:00'
            )
            """
        )

        ensure_employee_columns()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                status TEXT NOT NULL,
                notes TEXT,
                check_in_time TEXT,
                check_out_time TEXT,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )
        ensure_attendance_columns()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS discounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                reason TEXT,
                date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leave_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                days INTEGER NOT NULL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS salary_adjustments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                adjustment_type TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                reason TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                month TEXT NOT NULL,
                amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                paid_at TEXT,
                notes TEXT,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL DEFAULT ''
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employee_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                changed_by TEXT NOT NULL DEFAULT 'system',
                reason TEXT,
                notes TEXT,
                changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )
        ensure_status_history_columns()

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS employee_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                document_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'missing',
                assigned_to TEXT,
                request_date TEXT,
                updated_at TEXT,
                notes TEXT,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recruitment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_title TEXT NOT NULL,
                department TEXT,
                manager TEXT,
                vacancies INTEGER NOT NULL DEFAULT 1,
                requirements TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recruitment_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recruitment_request_id INTEGER NOT NULL,
                full_name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                education TEXT,
                specialization TEXT,
                experience_years INTEGER DEFAULT 0,
                target_position TEXT,
                cv_document TEXT,
                application_date TEXT NOT NULL DEFAULT CURRENT_DATE,
                stage TEXT NOT NULL DEFAULT 'new',
                interview_date TEXT,
                interviewer_name TEXT,
                evaluation TEXT,
                notes TEXT,
                outcome TEXT,
                FOREIGN KEY(recruitment_request_id) REFERENCES recruitment_requests(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS offboarding_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                departure_type TEXT NOT NULL,
                reason TEXT,
                request_date TEXT NOT NULL,
                last_work_day TEXT,
                assigned_to TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                clearance_status TEXT NOT NULL DEFAULT 'incomplete',
                notes TEXT,
                FOREIGN KEY(employee_id) REFERENCES employees(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS offboarding_clearance_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                offboarding_id INTEGER NOT NULL,
                item_name TEXT NOT NULL,
                responsible_person TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                completed_at TEXT,
                notes TEXT,
                FOREIGN KEY(offboarding_id) REFERENCES offboarding_requests(id) ON DELETE CASCADE
            )
            """
        )

        conn.commit()

        ensure_payroll_tables()
        ensure_employee_salary_defaults()

        default_settings = {
            "maintenance_mode": "false",
            "login_disabled": "false",
            "system_version": "1.0.0",
            "last_error": "No errors recorded.",
        }
        for key, value in default_settings.items():
            existing = conn.execute("SELECT 1 FROM system_settings WHERE setting_key = ?", (key,)).fetchone()
            if not existing:
                conn.execute("INSERT INTO system_settings (setting_key, setting_value) VALUES (?, ?)", (key, str(value)))

        admin_exists = conn.execute("SELECT 1 FROM users WHERE email = ? LIMIT 1", ("admin@hr.local",)).fetchone()
        if not admin_exists:
            conn.execute(
                "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                ("System Administrator", "admin@hr.local", generate_password_hash("admin123"), "admin"),
            )

        conn.commit()

        ensure_employee_document_defaults()


def add_user(full_name, email, password_hash, role="employee"):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO users (full_name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (full_name, email, password_hash, role),
        )
        conn.commit()
        return cursor.lastrowid


def get_user_by_email(email):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def add_employee(full_name, role, phone, base_salary, work_hours, hire_date, status="active", employment_type="full_time", notes="", check_in_time="08:00", check_out_time="17:00", employee_number=None, department=""):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO employees (full_name, role, phone, base_salary, work_hours, hire_date, status, employment_type, notes, check_in_time, check_out_time, employee_number, department) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (full_name, role, phone, base_salary, work_hours, hire_date, status, employment_type, notes, check_in_time, check_out_time, employee_number, department),
        )
        employee_id = cursor.lastrowid
        conn.commit()
    log_employee_status_change(employee_id, "new", status, "system", "إضافة موظف جديد", "إضافة موظف جديد")
    return employee_id


def get_employees(search=None, status=None):
    with get_connection() as conn:
        query = "SELECT * FROM employees"
        params = []
        clauses = []

        if search:
            clauses.append("(full_name LIKE ? OR role LIKE ? OR employee_number LIKE ? OR department LIKE ?)")
            like_term = f"%{search}%"
            params.extend([like_term, like_term, like_term, like_term])

        if status and status != "all":
            clauses.append("status = ?")
            params.append(status)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        query += " ORDER BY full_name ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_employee_by_id(employee_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return dict(row) if row else None


def update_employee(employee_id, data):
    current = get_employee_by_id(employee_id)
    previous_status = current.get("status", "active") if current else "active"
    with get_connection() as conn:
        conn.execute(
            "UPDATE employees SET full_name = ?, role = ?, phone = ?, employee_number = ?, department = ?, base_salary = ?, work_hours = ?, hire_date = ?, status = ?, employment_type = ?, notes = ?, check_in_time = ?, check_out_time = ? WHERE id = ?",
            (
                data["full_name"],
                data["role"],
                data["phone"],
                data.get("employee_number", current.get("employee_number") if current else None),
                data.get("department", current.get("department") if current else ""),
                data["base_salary"],
                data["work_hours"],
                data["hire_date"],
                data.get("status", "active"),
                data.get("employment_type", "full_time"),
                data.get("notes", ""),
                data.get("check_in_time", "08:00"),
                data.get("check_out_time", "17:00"),
                employee_id,
            ),
        )
        conn.commit()
    new_status = data.get("status", previous_status)
    reason = data.get("reason") or data.get("status_reason") or "تحديث بيانات الموظف"
    log_employee_status_change(employee_id, previous_status, new_status, "admin", reason, data.get("notes", ""))


def delete_employee(employee_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        conn.commit()


def add_attendance_record(employee_id, attendance_date, status, notes="", check_in_time=None, check_out_time=None):
    if status not in {"present", "absent", "late", "left"}:
        status = "present"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO attendance_records (employee_id, date, status, notes, check_in_time, check_out_time) VALUES (?, ?, ?, ?, ?, ?)",
            (employee_id, attendance_date, status, notes, check_in_time, check_out_time),
        )
        conn.commit()


def get_recent_attendance(limit=10):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT ar.id, ar.date, ar.status, ar.notes, ar.check_in_time, ar.check_out_time, e.full_name, e.role
            FROM attendance_records ar
            JOIN employees e ON e.id = ar.employee_id
            ORDER BY ar.date DESC, ar.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_active_employees(limit=None):
    with get_connection() as conn:
        query = "SELECT * FROM employees WHERE status = 'active' ORDER BY full_name ASC"
        params = []
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_employee_last_attendance(employee_id):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT date, status, check_in_time, check_out_time
            FROM attendance_records
            WHERE employee_id = ?
            ORDER BY date DESC, id DESC
            LIMIT 1
            """,
            (employee_id,),
        ).fetchone()
        return dict(row) if row else None


def get_employee_late_days(employee_id, month=None):
    with get_connection() as conn:
        if month:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM attendance_records WHERE employee_id = ? AND strftime('%Y-%m', date) = ? AND status = 'late'",
                (employee_id, month),
            ).fetchone()
            return int(row["total"]) if row else 0
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM attendance_records WHERE employee_id = ? AND status = 'late'",
            (employee_id,),
        ).fetchone()
        return int(row["total"]) if row else 0


def get_most_punctual_employees(limit=5):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.full_name, e.role, e.status,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND ar.status = 'late'), 0) AS late_days,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND ar.status = 'present'), 0) AS present_days,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND ar.status = 'absent'), 0) AS absent_days,
                   COALESCE((SELECT MAX(date) FROM attendance_records ar WHERE ar.employee_id = e.id), '') AS last_attendance_date
            FROM employees e
            ORDER BY late_days ASC, absent_days ASC, present_days DESC, e.full_name ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_system_settings():
    with get_connection() as conn:
        rows = conn.execute("SELECT setting_key, setting_value FROM system_settings").fetchall()
        settings = {}
        for row in rows:
            settings[row["setting_key"]] = row["setting_value"]
        return settings


def save_system_setting(key, value):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO system_settings (setting_key, setting_value) VALUES (?, ?) ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value",
            (key, str(value)),
        )
        conn.commit()


def check_database_connection():
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def ensure_status_history_columns():
    with get_connection() as conn:
        columns = conn.execute("PRAGMA table_info(employee_status_history)").fetchall()
        existing = {row[1] for row in columns}
        if "reason" not in existing:
            conn.execute("ALTER TABLE employee_status_history ADD COLUMN reason TEXT")
        if "notes" not in existing:
            conn.execute("ALTER TABLE employee_status_history ADD COLUMN notes TEXT")


def ensure_employee_document_defaults():
    default_documents = [
        "بطاقة الهوية",
        "إقرار العمل",
        "عقد العمل",
        "شهادة التدريب",
        "إيصال الراتب",
    ]
    with get_connection() as conn:
        employees = conn.execute("SELECT id, full_name FROM employees").fetchall()
        for employee in employees:
            for doc_name in default_documents:
                existing = conn.execute(
                    "SELECT id FROM employee_documents WHERE employee_id = ? AND document_name = ?",
                    (employee["id"], doc_name),
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO employee_documents (employee_id, document_name, status, assigned_to, request_date, updated_at, notes) VALUES (?, ?, 'missing', ?, ?, ?, 'مستند جديد')",
                        (employee["id"], doc_name, employee["full_name"], datetime.today().strftime("%Y-%m-%d"), datetime.today().strftime("%Y-%m-%d")),
                    )
        conn.commit()


def get_employee_document_summary():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.full_name, e.role, e.status,
                   COUNT(ed.id) AS total_documents,
                   SUM(CASE WHEN ed.status = 'complete' THEN 1 ELSE 0 END) AS completed_documents,
                   ROUND(
                       (SUM(CASE WHEN ed.status = 'complete' THEN 1 ELSE 0 END) * 100.0) / NULLIF(COUNT(ed.id), 0),
                       2
                   ) AS completion_percent,
                   GROUP_CONCAT(CASE WHEN ed.status != 'complete' THEN ed.document_name END, ', ') AS missing_documents
            FROM employees e
            LEFT JOIN employee_documents ed ON ed.employee_id = e.id
            GROUP BY e.id, e.full_name, e.role, e.status
            ORDER BY completion_percent ASC, e.full_name ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def add_employee_document(employee_id, document_name, status="missing", assigned_to="", request_date=None, notes=""):
    with get_connection() as conn:
        today = datetime.today().strftime("%Y-%m-%d")
        conn.execute(
            """
            INSERT INTO employee_documents (employee_id, document_name, status, assigned_to, request_date, updated_at, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (employee_id, document_name, status, assigned_to, request_date or today, today, notes),
        )
        conn.commit()


def update_employee_document_status(document_id, status):
    with get_connection() as conn:
        conn.execute(
            "UPDATE employee_documents SET status = ?, updated_at = ? WHERE id = ?",
            (status, datetime.today().strftime("%Y-%m-%d"), document_id),
        )
        conn.commit()


def get_employee_status_history(employee_id=None):
    with get_connection() as conn:
        query = """
            SELECT h.id, h.employee_id, e.full_name, h.old_status, h.new_status, h.changed_by, h.reason, h.notes, h.changed_at
            FROM employee_status_history h
            JOIN employees e ON e.id = h.employee_id
        """
        params = []
        if employee_id:
            query += " WHERE h.employee_id = ?"
            params.append(employee_id)
        query += " ORDER BY h.changed_at DESC, h.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def log_employee_status_change(employee_id, old_status, new_status, changed_by="system", reason="", notes=""):
    if not employee_id or old_status == new_status:
        return
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO employee_status_history (employee_id, old_status, new_status, changed_by, reason, notes, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (employee_id, old_status, new_status, changed_by, reason, notes, datetime.today().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()


def add_leave_request(employee_id, start_date, end_date, reason, status="pending"):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    days = (end - start).days + 1
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO leave_requests (employee_id, start_date, end_date, days, reason, status) VALUES (?, ?, ?, ?, ?, ?)",
            (employee_id, start_date, end_date, days, reason, status),
        )
        conn.commit()


def update_leave_request_status(leave_id, status):
    with get_connection() as conn:
        conn.execute(
            "UPDATE leave_requests SET status = ? WHERE id = ?",
            (status, leave_id),
        )
        conn.commit()


def get_leave_requests(limit=10, status=None):
    with get_connection() as conn:
        query = """
            SELECT lr.id, lr.start_date, lr.end_date, lr.days, lr.reason, lr.status, e.full_name, e.role
            FROM leave_requests lr
            JOIN employees e ON e.id = lr.employee_id
        """
        params = []
        if status and status != "all":
            query += " WHERE lr.status = ?"
            params.append(status)
        query += " ORDER BY lr.start_date DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def add_salary_adjustment(employee_id, adjustment_type, amount, reason):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO salary_adjustments (employee_id, adjustment_type, amount, reason) VALUES (?, ?, ?, ?)",
            (employee_id, adjustment_type, amount, reason),
        )
        conn.commit()


def add_discount(employee_id, amount, reason, date):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO discounts (employee_id, amount, reason, date) VALUES (?, ?, ?, ?)",
            (employee_id, amount, reason, date),
        )
        conn.commit()


def get_recent_discounts(limit=10):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.amount, d.reason, d.date, e.full_name, e.role
            FROM discounts d
            JOIN employees e ON e.id = d.employee_id
            ORDER BY d.date DESC, d.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_dashboard_summary(selected_month):
    with get_connection() as conn:
        employee_count = conn.execute("SELECT COUNT(*) AS total FROM employees").fetchone()["total"]
        present_count = conn.execute(
            "SELECT COUNT(*) AS total FROM attendance_records WHERE strftime('%Y-%m', date) = ? AND status = 'present'",
            (selected_month,),
        ).fetchone()["total"]
        absent_count = conn.execute(
            "SELECT COUNT(*) AS total FROM attendance_records WHERE strftime('%Y-%m', date) = ? AND status = 'absent'",
            (selected_month,),
        ).fetchone()["total"]
        late_count = conn.execute(
            "SELECT COUNT(*) AS total FROM attendance_records WHERE strftime('%Y-%m', date) = ? AND status = 'late'",
            (selected_month,),
        ).fetchone()["total"]
        left_count = conn.execute(
            "SELECT COUNT(*) AS total FROM attendance_records WHERE strftime('%Y-%m', date) = ? AND status = 'left'",
            (selected_month,),
        ).fetchone()["total"]
        total_payroll = conn.execute(
            "SELECT COALESCE(SUM(base_salary), 0) AS total FROM employees"
        ).fetchone()["total"]
        total_adjustments = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM salary_adjustments WHERE strftime('%Y-%m', created_at) = ?",
            (selected_month,),
        ).fetchone()["total"]
        total_discounts = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM discounts WHERE strftime('%Y-%m', date) = ?",
            (selected_month,),
        ).fetchone()["total"]
        total_leave_days = conn.execute(
            "SELECT COALESCE(SUM(days), 0) AS total FROM leave_requests WHERE strftime('%Y-%m', start_date) = ?",
            (selected_month,),
        ).fetchone()["total"]
        paid_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payroll_payouts WHERE month = ? AND status = 'paid'",
            (selected_month,),
        ).fetchone()["total"]
        pending_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM payroll_payouts WHERE month = ? AND status = 'pending'",
            (selected_month,),
        ).fetchone()["total"]

    return {
        "employees": employee_count,
        "present": present_count,
        "absent": absent_count,
        "late": late_count,
        "left": left_count,
        "payroll": total_payroll,
        "adjustments": total_adjustments,
        "discounts": total_discounts,
        "leave_days": total_leave_days,
        "paid_total": paid_total,
        "pending_total": pending_total,
    }


def get_alerts(selected_month):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT e.id, e.full_name, e.role, e.status,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND strftime('%Y-%m', ar.date)=? AND ar.status='late'), 0) AS late_days,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND strftime('%Y-%m', ar.date)=? AND ar.status='absent'), 0) AS absent_days,
                   COALESCE((SELECT SUM(days) FROM leave_requests lr WHERE lr.employee_id = e.id AND strftime('%Y-%m', lr.start_date)=?), 0) AS leave_days
            FROM employees e
            ORDER BY e.full_name ASC
            """,
            (selected_month, selected_month, selected_month),
        ).fetchall()

        alerts = []
        for row in rows:
            if row["late_days"] > 0:
                alerts.append({
                    "type": "late",
                    "title": "تأخر/تأخيرات",
                    "message": f"{row['full_name']} لديه {row['late_days']} تأخر في {selected_month}",
                    "employee_id": row['id'],
                })
            if row["absent_days"] > 0:
                alerts.append({
                    "type": "absence",
                    "title": "غياب",
                    "message": f"{row['full_name']} لديه {row['absent_days']} غياب في {selected_month}",
                    "employee_id": row['id'],
                })
            if row["leave_days"] > 0:
                alerts.append({
                    "type": "leave",
                    "title": "إجازة",
                    "message": f"{row['full_name']} لديه {row['leave_days']} يوم إجازة في {selected_month}",
                    "employee_id": row['id'],
                })
        return alerts


def add_payroll_payout(employee_id, month, amount, status="pending", notes=""):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO payroll_payouts (employee_id, month, amount, status, paid_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
            (employee_id, month, amount, status, datetime.today().strftime("%Y-%m-%d") if status == "paid" else None, notes),
        )
        conn.commit()


def get_payroll_payouts(month=None):
    with get_connection() as conn:
        query = """
            SELECT pp.id, pp.employee_id, pp.month, pp.amount, pp.status, pp.paid_at, pp.notes, e.full_name, e.role
            FROM payroll_payouts pp
            JOIN employees e ON e.id = pp.employee_id
        """
        params = []
        if month:
            query += " WHERE pp.month = ?"
            params.append(month)
        query += " ORDER BY pp.month DESC, e.full_name ASC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def update_payroll_status(employee_id, month, status="paid"):
    with get_connection() as conn:
        conn.execute(
            "UPDATE payroll_payouts SET status = ?, paid_at = ? WHERE employee_id = ? AND month = ?",
            (status, datetime.today().strftime("%Y-%m-%d") if status == "paid" else None, employee_id, month),
        )
        conn.commit()


def get_monthly_report(selected_month, employee_id=None):
    with get_connection() as conn:
        base_query = """
            SELECT e.id, e.full_name, e.role, e.base_salary, e.status, e.employment_type,
                   COALESCE((SELECT SUM(amount) FROM salary_adjustments sa WHERE sa.employee_id = e.id AND strftime('%Y-%m', sa.created_at) = ?), 0) AS adjustment_total,
                   COALESCE((SELECT SUM(amount) FROM discounts d WHERE d.employee_id = e.id AND strftime('%Y-%m', d.date) = ?), 0) AS discount_total,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND strftime('%Y-%m', ar.date) = ? AND ar.status = 'present'), 0) AS present_days,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND strftime('%Y-%m', ar.date) = ? AND ar.status = 'absent'), 0) AS absent_days,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND strftime('%Y-%m', ar.date) = ? AND ar.status = 'late'), 0) AS late_days,
                   COALESCE((SELECT COUNT(*) FROM attendance_records ar WHERE ar.employee_id = e.id AND strftime('%Y-%m', ar.date) = ? AND ar.status = 'left'), 0) AS left_days,
                   COALESCE((SELECT SUM(days) FROM leave_requests lr WHERE lr.employee_id = e.id AND strftime('%Y-%m', lr.start_date) = ?), 0) AS leave_days
            FROM employees e
        """
        params = [selected_month, selected_month, selected_month, selected_month, selected_month, selected_month, selected_month]

        if employee_id:
            base_query += " WHERE e.id = ?"
            params.append(employee_id)

        base_query += " ORDER BY e.full_name ASC"
        rows = conn.execute(base_query, params).fetchall()

        result = []
        for row in rows:
            base_salary = float(row["base_salary"])
            adjustments = float(row["adjustment_total"])
            discounts = float(row["discount_total"])
            total_salary = base_salary + adjustments - discounts
            result.append({
                "id": row["id"],
                "full_name": row["full_name"],
                "role": row["role"],
                "base_salary": base_salary,
                "status": row["status"],
                "employment_type": row["employment_type"],
                "adjustment_total": adjustments,
                "discount_total": discounts,
                "present_days": row["present_days"],
                "absent_days": row["absent_days"],
                "late_days": row["late_days"],
                "left_days": row["left_days"],
                "leave_days": row["leave_days"],
                "total_salary": total_salary,
            })
        return result


def add_recruitment_request(position_title, department, manager, vacancies, requirements, status="new"):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO recruitment_requests (position_title, department, manager, vacancies, requirements, status) VALUES (?, ?, ?, ?, ?, ?)",
            (position_title, department, manager, vacancies, requirements, status),
        )
        conn.commit()
        return cursor.lastrowid


def get_recruitment_requests(status=None):
    with get_connection() as conn:
        query = "SELECT * FROM recruitment_requests"
        params = []
        if status and status != "all":
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def add_recruitment_candidate(recruitment_request_id, full_name, phone, email, education, specialization, experience_years, target_position, cv_document, stage="new", interview_date=None, interviewer_name="", evaluation="", notes="", outcome=""):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO recruitment_candidates (recruitment_request_id, full_name, phone, email, education, specialization, experience_years, target_position, cv_document, stage, interview_date, interviewer_name, evaluation, notes, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (recruitment_request_id, full_name, phone, email, education, specialization, experience_years, target_position, cv_document, stage, interview_date, interviewer_name, evaluation, notes, outcome),
        )
        conn.commit()
        return cursor.lastrowid


def get_recruitment_candidates(recruitment_request_id=None):
    with get_connection() as conn:
        query = """
            SELECT c.*, r.position_title
            FROM recruitment_candidates c
            LEFT JOIN recruitment_requests r ON r.id = c.recruitment_request_id
        """
        params = []
        if recruitment_request_id:
            query += " WHERE c.recruitment_request_id = ?"
            params.append(recruitment_request_id)
        query += " ORDER BY c.application_date DESC, c.id DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def hire_candidate(candidate_id):
    with get_connection() as conn:
        candidate = conn.execute("SELECT * FROM recruitment_candidates WHERE id = ?", (candidate_id,)).fetchone()
        if not candidate:
            return None

        employee_number = f"EMP-{datetime.today().strftime('%Y%m%d')}-{candidate['id']}"
        employee_id = conn.execute(
            "INSERT INTO employees (full_name, role, phone, employee_number, department, base_salary, work_hours, hire_date, status, employment_type, notes, check_in_time, check_out_time) VALUES (?, ?, ?, ?, ?, 0, 8, ?, 'active', 'full_time', ?, '08:00', '17:00')",
            (
                candidate["full_name"],
                candidate["target_position"],
                candidate["phone"],
                employee_number,
                candidate["specialization"],
                datetime.today().strftime("%Y-%m-%d"),
                f"تمت الموافقة بناءً على طلب التوظيف - {candidate['target_position']}",
            ),
        ).lastrowid
        conn.execute("UPDATE recruitment_candidates SET stage = 'hired', outcome = 'accepted' WHERE id = ?", (candidate_id,))
        conn.commit()
        log_employee_status_change(employee_id, "new", "active", "system", "التوظيف من الطلب", "تم تحويل المرشح إلى موظف")
        return employee_id


def add_offboarding_request(employee_id, departure_type, reason, request_date, last_work_day, assigned_to, status="pending", notes=""):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO offboarding_requests (employee_id, departure_type, reason, request_date, last_work_day, assigned_to, status, clearance_status, notes) VALUES (?, ?, ?, ?, ?, ?, ?, 'incomplete', ?)",
            (employee_id, departure_type, reason, request_date, last_work_day, assigned_to, status, notes),
        )
        conn.commit()
        return cursor.lastrowid


def get_offboarding_requests(status=None):
    with get_connection() as conn:
        query = """
            SELECT o.*, e.full_name, e.role, e.employee_number
            FROM offboarding_requests o
            JOIN employees e ON e.id = o.employee_id
        """
        params = []
        if status and status != "all":
            query += " WHERE o.status = ?"
            params.append(status)
        query += " ORDER BY o.request_date DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def add_clearance_item(offboarding_id, item_name, responsible_person="", status="pending", notes=""):
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO offboarding_clearance_items (offboarding_id, item_name, responsible_person, status, notes) VALUES (?, ?, ?, ?, ?)",
            (offboarding_id, item_name, responsible_person, status, notes),
        )
        conn.commit()
        return cursor.lastrowid


def get_offboarding_clearance_items(offboarding_id):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM offboarding_clearance_items WHERE offboarding_id = ? ORDER BY id ASC",
            (offboarding_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def update_clearance_item(item_id, status, notes=""):
    with get_connection() as conn:
        conn.execute(
            "UPDATE offboarding_clearance_items SET status = ?, completed_at = ?, notes = ? WHERE id = ?",
            (status, datetime.today().strftime("%Y-%m-%d"), notes, item_id),
        )
        conn.commit()


def finalize_offboarding_request(offboarding_id):
    with get_connection() as conn:
        request = conn.execute("SELECT * FROM offboarding_requests WHERE id = ?", (offboarding_id,)).fetchone()
        if not request:
            return None

        mapping = {
            "resignation": "resigned",
            "termination": "terminated",
            "retirement": "retired",
            "contract_end": "terminated",
        }
        new_status = mapping.get(request["departure_type"], "resigned")
        conn.execute("UPDATE offboarding_requests SET status = 'approved', clearance_status = 'completed' WHERE id = ?", (offboarding_id,))
        conn.execute("UPDATE employees SET status = ? WHERE id = ?", (new_status, request["employee_id"]))
        conn.commit()
        log_employee_status_change(request["employee_id"], "active", new_status, "admin", request["reason"] or "مغادرة موظف", request["notes"] or "تم اعتماد المغادرة")
        return new_status
