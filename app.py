import platform
import sqlite3
from datetime import datetime
from io import BytesIO

from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    add_attendance_record,
    add_clearance_item,
    add_discount,
    add_employee,
    add_friday_overtime,
    add_holiday_overtime,
    add_leave_request,
    add_offboarding_request,
    add_overtime_request,
    add_payroll_payout,
    add_recruitment_candidate,
    add_recruitment_request,
    add_salary_adjustment,
    add_user,
    delete_employee,
    finalize_offboarding_request,
    generate_monthly_payroll,
    get_alerts,
    get_dashboard_summary,
    get_employee_by_id,
    get_employee_document_summary,
    get_employee_last_attendance,
    get_employee_late_days,
    get_employee_late_summary,
    get_employee_status_history,
    get_employees,
    get_friday_overtime,
    get_holiday_overtime,
    get_leave_requests,
    get_monthly_report,
    get_most_punctual_employees,
    get_offboarding_clearance_items,
    get_offboarding_requests,
    get_overtime_requests,
    get_payroll_payouts,
    get_payroll_records,
    get_recent_attendance,
    get_recent_discounts,
    get_recruitment_candidates,
    get_recruitment_requests,
    get_salary_settings,
    get_system_settings,
    get_user_by_email,
    hire_candidate,
    init_db,
    save_salary_settings,
    save_system_setting,
    check_database_connection,
    update_clearance_item,
    update_employee,
    update_employee_document_status,
    update_leave_request_status,
    update_overtime_status,
    update_payroll_record_status,
    update_payroll_status,
)

app = Flask(__name__)
app.secret_key = "hr-system-secret-key-2026"
app.config["SYSTEM_VERSION"] = "1.0.0"
app.config["MAINTENANCE_MODE"] = False
app.config["LOGIN_DISABLED"] = False
app.config["LAST_ERROR"] = "No errors recorded."

init_db()

settings = get_system_settings()
app.config["MAINTENANCE_MODE"] = str(settings.get("maintenance_mode", "false")).lower() == "true"
app.config["LOGIN_DISABLED"] = str(settings.get("login_disabled", "false")).lower() == "true"
app.config["SYSTEM_VERSION"] = settings.get("system_version", app.config.get("SYSTEM_VERSION", "1.0.0"))
app.config["LAST_ERROR"] = settings.get("last_error", app.config.get("LAST_ERROR", "No errors recorded."))


@app.before_request
def enforce_maintenance_mode():
    allowed_endpoints = {"login", "register", "logout", "developer_tools", "static"}
    if app.config.get("MAINTENANCE_MODE") and request.endpoint not in allowed_endpoints:
        if session.get("user_role") == "admin":
            return None
        return render_template("maintenance.html"), 503


def normalize_role(role):
    normalized = (role or "").strip().lower().replace("-", "_").replace(" ", "_")
    role_aliases = {
        "admin": "hr",
        "manager": "hr",
        "hr": "hr",
        "human_resources": "hr",
        "system_designer": "system_designer",
        "designer": "system_designer",
        "systemdesigner": "system_designer",
        "employee": "employee",
    }
    return role_aliases.get(normalized, normalized or "employee")


def role_label(role):
    display_names = {
        "hr": "HR",
        "system_designer": "مصمم نظام",
        "employee": "Employee",
    }
    return display_names.get(normalize_role(role), "Employee")


def user_has_role(*roles):
    current_role = normalize_role(session.get("user_role", "employee"))
    valid_roles = {normalize_role(role) for role in roles}
    return current_role in valid_roles


@app.route("/")
def home():
    if "user_id" in session:
        if normalize_role(session.get("user_role", "employee")) == "system_designer":
            return redirect(url_for("developer_tools"))
        return redirect(url_for("dashboard"))
    return redirect(url_for("landing"))


@app.route("/landing")
def landing():
    return render_template("landing.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if app.config.get("MAINTENANCE_MODE"):
        flash("النظام في وضع الصيانة، تم تعليق تسجيل الدخول مؤقتاً.", "error")
        return render_template("login.html")

    if app.config.get("LOGIN_DISABLED"):
        flash("تم تعطيل تسجيل الدخول مؤقتاً من قبل المسؤول.", "error")
        return render_template("login.html")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        selected_role = normalize_role(request.form.get("role"))

        if not email or not password:
            flash("Please enter your email and password.", "error")
            return render_template("login.html")

        user = get_user_by_email(email)
        if user and check_password_hash(user["password_hash"], password):
            user_role = normalize_role(user.get("role", "employee"))
            if selected_role and user_role != selected_role:
                flash(
                    f"اسم المستخدم مسجل بصلاحية {role_label(user_role)}، ولا يمكنك الدخول بسبب الصلاحية المختارة {role_label(selected_role)}.",
                    "error",
                )
                return render_template("login.html")

            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            session["user_role"] = user_role
            flash(f"Welcome back, {user['full_name']}!", "success")
            if user_role == "system_designer":
                return redirect(url_for("developer_tools"))
            return redirect(url_for("dashboard"))

        save_system_setting("last_error", "Invalid email or password.")
        flash("Invalid email or password.", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        role = normalize_role(request.form.get("role", "employee"))

        if not full_name or not email or not password or not confirm_password:
            flash("Please complete all fields.", "error")
            return render_template("register.html")

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html")

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("register.html")

        if get_user_by_email(email):
            flash("This email is already registered. Please sign in.", "error")
            return redirect(url_for("login"))

        try:
            add_user(full_name, email, generate_password_hash(password), role)
        except sqlite3.IntegrityError:
            flash("This email is already registered. Please sign in.", "error")
            return redirect(url_for("login"))

        flash("Account created successfully. Please sign in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/developer-tools", methods=["GET", "POST"])
def developer_tools():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not user_has_role("system_designer", "admin"):
        flash("ليس لديك صلاحية إدارة أدوات المصمم.", "error")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "toggle_maintenance":
            maintenance = request.form.get("maintenance_mode") == "on"
            save_system_setting("maintenance_mode", str(maintenance).lower())
            app.config["MAINTENANCE_MODE"] = maintenance
            flash("تم تحديث وضع الصيانة بنجاح.", "success")
        elif action == "toggle_login":
            login_disabled = request.form.get("login_disabled") == "on"
            save_system_setting("login_disabled", str(login_disabled).lower())
            app.config["LOGIN_DISABLED"] = login_disabled
            flash("تم تحديث تعطيل تسجيل الدخول بنجاح.", "success")
        elif action == "update_version":
            version = request.form.get("system_version", "1.0.0").strip() or "1.0.0"
            save_system_setting("system_version", version)
            app.config["SYSTEM_VERSION"] = version
            flash("تم تحديث نسخة النظام بنجاح.", "success")
        elif action == "clear_error":
            save_system_setting("last_error", "No errors recorded.")
            app.config["LAST_ERROR"] = "No errors recorded."
            flash("تمت إعادة تعيين رسائل الأخطاء.", "success")
        return redirect(url_for("developer_tools"))

    settings = get_system_settings()
    db_ok = check_database_connection()
    return render_template(
        "developer_tools.html",
        user_name=session.get("user_name", "User"),
        system_version=settings.get("system_version", app.config.get("SYSTEM_VERSION", "1.0.0")),
        maintenance_mode=str(settings.get("maintenance_mode", "false")).lower() == "true",
        login_disabled=str(settings.get("login_disabled", "false")).lower() == "true",
        last_error=settings.get("last_error", app.config.get("LAST_ERROR", "No errors recorded.")),
        database_ok=db_ok,
        python_version=platform.python_version(),
        flask_version=__import__("flask").__version__,
    )


@app.route("/documents", methods=["GET", "POST"])
def documents():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_document_status":
            document_id = request.form.get("document_id")
            status = request.form.get("status", "missing")
            if document_id:
                update_employee_document_status(document_id, status)
                flash("تم تحديث حالة المستند بنجاح.", "success")
        return redirect(url_for("documents"))

    summary = get_employee_document_summary()
    return render_template(
        "documents.html",
        user_name=session.get("user_name", "User"),
        summary=summary,
    )


@app.route("/employee-history/<int:employee_id>")
def employee_history(employee_id):
    if "user_id" not in session:
        return redirect(url_for("login"))
    employee = get_employee_by_id(employee_id)
    history = get_employee_status_history(employee_id)
    return render_template(
        "employee_history.html",
        user_name=session.get("user_name", "User"),
        employee=employee,
        history=history,
    )


@app.route("/employees/<int:employee_id>/status", methods=["POST"])
def employee_status_update(employee_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    employee = get_employee_by_id(employee_id)
    if not employee:
        flash("الموظف غير موجود.", "error")
        return redirect(url_for("employees"))

    status = request.form.get("status")
    if not status:
        flash("يرجى اختيار حالة الموظف.", "error")
        return redirect(url_for("employee_history", employee_id=employee_id))

    employee_data = dict(employee)
    employee_data["status"] = status
    employee_data["reason"] = request.form.get("reason", "")
    employee_data["notes"] = request.form.get("notes", employee.get("notes", ""))
    update_employee(employee_id, employee_data)
    flash("تم تحديث حالة الموظف وسجل التغييرات بنجاح.", "success")
    return redirect(url_for("employee_history", employee_id=employee_id))


@app.route("/recruitment", methods=["GET", "POST"])
def recruitment():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_request":
            title = request.form.get("position_title", "").strip()
            department = request.form.get("department", "").strip()
            manager = request.form.get("manager", "").strip()
            vacancies = request.form.get("vacancies", "1").strip()
            requirements = request.form.get("requirements", "").strip()
            status = request.form.get("status", "new")
            if title:
                add_recruitment_request(title, department, manager, int(vacancies or 1), requirements, status)
                flash("تم إنشاء طلب التوظيف بنجاح.", "success")
            else:
                flash("يرجى إدخال المسمى الوظيفي.", "error")
        elif action == "add_candidate":
            request_id = request.form.get("recruitment_request_id")
            full_name = request.form.get("full_name", "").strip()
            email = request.form.get("email", "").strip()
            if request_id and full_name:
                add_recruitment_candidate(
                    request_id,
                    full_name,
                    request.form.get("phone", "").strip(),
                    email,
                    request.form.get("education", "").strip(),
                    request.form.get("specialization", "").strip(),
                    int(request.form.get("experience_years", 0) or 0),
                    request.form.get("target_position", "").strip(),
                    request.form.get("cv_document", "").strip(),
                    request.form.get("stage", "new"),
                    request.form.get("interview_date"),
                    request.form.get("interviewer_name", "").strip(),
                    request.form.get("evaluation", "").strip(),
                    request.form.get("notes", "").strip(),
                    request.form.get("outcome", "").strip(),
                )
                flash("تمت إضافة المتقدم بنجاح.", "success")
            else:
                flash("يرجى إدخال اسم المتقدم ورقم الطلب.", "error")
        elif action == "hire_candidate":
            candidate_id = request.form.get("candidate_id")
            if candidate_id:
                employee_id = hire_candidate(candidate_id)
                if employee_id:
                    flash("تم تحويل المتقدم إلى موظف جديد بنجاح.", "success")
                else:
                    flash("تعذر تحويل المتقدم إلى موظف.", "error")
        return redirect(url_for("recruitment"))

    requests = get_recruitment_requests()
    candidates_by_request = {}
    for req in requests:
        candidates_by_request[req["id"]] = get_recruitment_candidates(req["id"])
    return render_template(
        "recruitment.html",
        user_name=session.get("user_name", "User"),
        requests=requests,
        candidates_by_request=candidates_by_request,
    )


@app.route("/offboarding", methods=["GET", "POST"])
def offboarding():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "create_request":
            employee_id = request.form.get("employee_id")
            departure_type = request.form.get("departure_type")
            reason = request.form.get("reason", "").strip()
            request_date = request.form.get("request_date") or datetime.today().strftime("%Y-%m-%d")
            last_work_day = request.form.get("last_work_day")
            assigned_to = request.form.get("assigned_to", "").strip()
            if employee_id and departure_type:
                offboarding_id = add_offboarding_request(employee_id, departure_type, reason, request_date, last_work_day, assigned_to, "pending", reason)
                default_checks = [
                    "تسليم العهد",
                    "تسليم الأجهزة",
                    "تسليم المعدات",
                    "تسليم بطاقة العمل",
                    "تسوية السلف",
                    "مراجعة المستحقات المالية",
                    "إغلاق صلاحيات الدخول",
                ]
                for item_name in default_checks:
                    add_clearance_item(offboarding_id, item_name, assigned_to or "HR Manager")
                flash("تم تسجيل طلب المغادرة بنجاح.", "success")
            else:
                flash("يرجى اختيار الموظف ونوع المغادرة.", "error")
        elif action == "update_clearance":
            item_id = request.form.get("item_id")
            status = request.form.get("status")
            notes = request.form.get("notes", "").strip()
            if item_id and status:
                update_clearance_item(item_id, status, notes)
                flash("تم تحديث عنصر الإخلاء بنجاح.", "success")
        elif action == "approve_offboarding":
            offboarding_id = request.form.get("offboarding_id")
            if offboarding_id:
                finalize_offboarding_request(offboarding_id)
                flash("تم اعتماد المغادرة وتحديث حالة الموظف.", "success")
        return redirect(url_for("offboarding"))

    employees = get_employees(status="all")
    requests = get_offboarding_requests()
    clearance_map = {}
    for item in requests:
        clearance_map[item["id"]] = get_offboarding_clearance_items(item["id"])
    return render_template(
        "offboarding.html",
        user_name=session.get("user_name", "User"),
        employees=employees,
        requests=requests,
        clearance_map=clearance_map,
    )


@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if normalize_role(session.get("user_role", "employee")) == "system_designer":
        return redirect(url_for("developer_tools"))

    if request.method == "POST":
        action = request.form.get("action")

        if action == "mark_payroll_paid":
            employee_id = request.form.get("employee_id")
            month = request.form.get("month") or datetime.today().strftime("%Y-%m")
            amount = float(request.form.get("amount", 0) or 0)
            notes = request.form.get("notes", "").strip()
            if employee_id and amount > 0:
                add_payroll_payout(employee_id, month, amount, "paid", notes)
                flash("تم تسجيل صرف الراتب بنجاح.", "success")
            else:
                flash("يرجى تحديد الموظف والمبلغ الصحيح.", "error")

        elif action == "add_employee":
            full_name = request.form.get("full_name", "").strip()
            role = request.form.get("role", "").strip()
            phone = request.form.get("phone", "").strip()
            base_salary = float(request.form.get("base_salary", 0) or 0)
            work_hours = float(request.form.get("work_hours", 0) or 0)
            hire_date = request.form.get("hire_date") or datetime.today().strftime("%Y-%m-%d")
            status = request.form.get("status", "active")
            employment_type = request.form.get("employment_type", "full_time")
            notes = request.form.get("notes", "").strip()
            check_in_time = request.form.get("check_in_time") or "08:00"
            check_out_time = request.form.get("check_out_time") or "17:00"

            status = request.form.get("status", "active")
            employment_type = request.form.get("employment_type", "full_time")
            notes = request.form.get("notes", "").strip()

            if full_name and role:
                add_employee(full_name, role, phone, base_salary, work_hours, hire_date, status, employment_type, notes, check_in_time, check_out_time)
                flash("تمت إضافة الموظف بنجاح.", "success")
            else:
                flash("اسم الموظف والوظيفة مطلوبان.", "error")

        elif action == "update_employee":
            employee_id = request.form.get("employee_id")
            if employee_id:
                data = {
                    "full_name": request.form.get("full_name", "").strip(),
                    "role": request.form.get("role", "").strip(),
                    "phone": request.form.get("phone", "").strip(),
                    "base_salary": float(request.form.get("base_salary", 0) or 0),
                    "work_hours": float(request.form.get("work_hours", 0) or 0),
                    "hire_date": request.form.get("hire_date") or datetime.today().strftime("%Y-%m-%d"),
                    "status": request.form.get("status", "active"),
                    "employment_type": request.form.get("employment_type", "full_time"),
                    "notes": request.form.get("notes", "").strip(),
                    "check_in_time": request.form.get("check_in_time") or "08:00",
                    "check_out_time": request.form.get("check_out_time") or "17:00",
                }
                if data["full_name"] and data["role"]:
                    update_employee(employee_id, data)
                    flash("تم تحديث بيانات الموظف بنجاح.", "success")
                else:
                    flash("اسم الموظف والوظيفة مطلوبان.", "error")

        elif action == "delete_employee":
            employee_id = request.form.get("employee_id")
            if employee_id:
                delete_employee(employee_id)
                flash("تم حذف الموظف بنجاح.", "success")

        elif action == "attendance":
            employee_id = request.form.get("employee_id")
            status = request.form.get("status")
            attendance_date = request.form.get("date") or datetime.today().strftime("%Y-%m-%d")
            notes = request.form.get("notes", "").strip()
            check_in_time = request.form.get("check_in_time")
            check_out_time = request.form.get("check_out_time")
            if employee_id and status:
                add_attendance_record(employee_id, attendance_date, status, notes, check_in_time, check_out_time)
                flash("تم حفظ الحضور والغياب بنجاح.", "success")
            else:
                flash("يرجى اختيار موظف وحالة الحضور.", "error")

        elif action == "discount":
            employee_id = request.form.get("employee_id")
            amount = float(request.form.get("amount", 0) or 0)
            reason = request.form.get("reason", "").strip()
            discount_date = request.form.get("date") or datetime.today().strftime("%Y-%m-%d")
            if employee_id and amount > 0:
                add_discount(employee_id, amount, reason, discount_date)
                flash("تم إضافة الخصم بنجاح.", "success")
            else:
                flash("يرجى اختيار موظف وكتابة قيمة خصم صحيحة.", "error")

        elif action == "leave":
            employee_id = request.form.get("employee_id")
            start_date = request.form.get("start_date")
            end_date = request.form.get("end_date")
            reason = request.form.get("reason", "").strip()
            if employee_id and start_date and end_date:
                add_leave_request(employee_id, start_date, end_date, reason)
                flash("تمت إضافة طلب الإجازة بنجاح.", "success")
            else:
                flash("يرجى اختيار الموظف وتحديد تواريخ الإجازة.", "error")

        elif action == "adjustment":
            employee_ids = request.form.getlist("employee_ids")
            adjustment_type = request.form.get("adjustment_type")
            amount = float(request.form.get("amount", 0) or 0)
            reason = request.form.get("reason", "").strip()
            if employee_ids and adjustment_type and amount > 0:
                for employee_id in employee_ids:
                    add_salary_adjustment(employee_id, adjustment_type, amount, reason)
                flash("تم تطبيق الزيادة/المكافأة بنجاح.", "success")
            else:
                flash("يرجى اختيار الموظفين وكتابة مبلغ صحيح.", "error")

        return redirect(url_for("dashboard"))

    selected_month = request.args.get("month") or datetime.today().strftime("%Y-%m")
    employees = get_employees(status="active")
    attendance = get_recent_attendance(limit=10)
    leaves = get_leave_requests(limit=10)
    discounts = get_recent_discounts(limit=10)
    summary = get_dashboard_summary(selected_month)
    report = get_monthly_report(selected_month)
    alerts = get_alerts(selected_month)
    payroll_rows = get_payroll_payouts(selected_month)
    punctual_employees = get_most_punctual_employees(limit=5)

    for employee in employees:
        attendance_data = get_employee_last_attendance(employee["id"])
        employee["last_attendance_date"] = attendance_data["date"] if attendance_data else "—"
        employee["last_attendance_status"] = attendance_data["status"] if attendance_data else "—"
        employee["late_days"] = get_employee_late_days(employee["id"], selected_month)

    return render_template(
        "dashboard.html",
        user_name=session.get("user_name", "User"),
        employees=employees,
        attendance=attendance,
        leaves=leaves,
        discounts=discounts,
        summary=summary,
        report=report,
        alerts=alerts,
        payroll_rows=payroll_rows,
        punctual_employees=punctual_employees,
        selected_month=selected_month,
    )


@app.route("/employees")
def employees():
    if "user_id" not in session:
        return redirect(url_for("login"))

    search = request.args.get("q", "").strip()
    status = request.args.get("status", "all")
    selected_month = request.args.get("month") or datetime.today().strftime("%Y-%m")
    status = request.args.get("status") or "active"
    employees_list = get_employees(search=search, status=status)
    for employee in employees_list:
        attendance_data = get_employee_last_attendance(employee["id"])
        employee["last_attendance_date"] = attendance_data["date"] if attendance_data else "—"
    return render_template(
        "employees.html",
        employees=employees_list,
        user_name=session.get("user_name", "User"),
        search=search,
        status=status,
        selected_month=selected_month,
    )


@app.route("/leaves", methods=["GET", "POST"])
def leaves():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "update_leave_status":
            if not user_has_role("admin", "manager"):
                flash("ليس لديك صلاحية تعديل حالة الإجازات.", "error")
                return redirect(url_for("leaves"))
            leave_id = request.form.get("leave_id")
            status = request.form.get("status")
            if leave_id and status:
                update_leave_request_status(leave_id, status)
                flash("تم تحديث حالة الإجازة بنجاح.", "success")
            return redirect(url_for("leaves"))

        employee_id = request.form.get("employee_id")
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        reason = request.form.get("reason", "").strip()
        if employee_id and start_date and end_date:
            add_leave_request(employee_id, start_date, end_date, reason)
            flash("تم تسجيل طلب الإجازة بنجاح.", "success")
        else:
            flash("يرجى تحديد الموظف وتواريخ الإجازة.", "error")
        return redirect(url_for("leaves"))

    selected_status = request.args.get("status", "all")
    employee_rows = get_employees()
    leave_rows = get_leave_requests(status=selected_status)
    return render_template(
        "leaves.html",
        user_name=session.get("user_name", "User"),
        user_role=session.get("user_role", "employee"),
        employees=employee_rows,
        leaves=leave_rows,
        selected_status=selected_status,
    )


@app.route("/reports")
def reports():
    if "user_id" not in session:
        return redirect(url_for("login"))

    selected_month = request.args.get("month") or datetime.today().strftime("%Y-%m")
    employee_id = request.args.get("employee_id")
    employees = get_employees()
    report = get_monthly_report(selected_month, employee_id) if employee_id else get_monthly_report(selected_month)
    alerts = get_alerts(selected_month)

    return render_template(
        "reports.html",
        user_name=session.get("user_name", "User"),
        employees=employees,
        report=report,
        alerts=alerts,
        selected_month=selected_month,
        selected_employee=employee_id,
    )


@app.route("/payroll-settings", methods=["GET", "POST"])
def payroll_settings():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        employee_id = request.form.get("employee_id")
        if employee_id:
            payload = {
                "basic_salary": request.form.get("basic_salary", 0),
                "working_days_per_month": request.form.get("working_days_per_month", 26),
                "work_hours_per_day": request.form.get("work_hours_per_day", 8),
                "work_hours_per_week": request.form.get("work_hours_per_week", 48),
                "official_work_days": request.form.get("official_work_days", "Sun-Thu"),
                "start_time": request.form.get("start_time", "08:00"),
                "end_time": request.form.get("end_time", "17:00"),
                "grace_period_minutes": request.form.get("grace_period_minutes", 10),
                "regular_hour_value": request.form.get("regular_hour_value", 0),
                "late_hour_value": request.form.get("late_hour_value", 0),
                "overtime_multiplier": request.form.get("overtime_multiplier", 1.5),
                "friday_overtime_multiplier": request.form.get("friday_overtime_multiplier", 2.0),
                "holiday_overtime_multiplier": request.form.get("holiday_overtime_multiplier", 2.5),
            }
            save_salary_settings(int(employee_id), payload, session.get("user_name", "system"))
            employee = get_employee_by_id(int(employee_id))
            if employee:
                employee["base_salary"] = float(payload.get("basic_salary") or employee.get("base_salary") or 0)
                update_employee(employee_id, employee)
            flash("تم حفظ إعدادات الرواتب بنجاح.", "success")
        return redirect(url_for("payroll_settings"))

    employees = get_employees(status="all")
    settings = []
    for employee in employees:
        settings.append({"employee": employee, "salary_settings": get_salary_settings(employee["id"])})
    return render_template("payroll_settings.html", user_name=session.get("user_name", "User"), settings=settings, employees=employees)


@app.route("/overtime", methods=["GET", "POST"])
def overtime():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action in {"approve", "reject"} and not user_has_role("admin", "manager"):
            flash("ليس لديك صلاحية اعتماد أو رفض الطلبات.", "error")
            return redirect(url_for("overtime"))

        if action == "create_request":
            employee_id = request.form.get("employee_id")
            if employee_id:
                record_id = add_overtime_request(
                    int(employee_id),
                    request.form.get("work_date"),
                    request.form.get("start_time"),
                    request.form.get("end_time"),
                    request.form.get("reason", ""),
                    session.get("user_name", "system"),
                    request.form.get("payroll_month") or datetime.today().strftime("%Y-%m"),
                )
                if record_id:
                    flash("تم إرسال طلب الساعات الإضافية بنجاح.", "success")
                else:
                    flash("تأكد من صحة بيانات الطلب الإضافي.", "error")
            else:
                flash("يرجى اختيار الموظف.", "error")
        elif action == "approve":
            record_id = request.form.get("record_id")
            if record_id:
                update_overtime_status(int(record_id), "approved", session.get("user_name", "system"))
                flash("تم اعتماد الطلب بنجاح.", "success")
        elif action == "reject":
            record_id = request.form.get("record_id")
            if record_id:
                update_overtime_status(int(record_id), "rejected", session.get("user_name", "system"))
                flash("تم رفض الطلب بنجاح.", "success")
        return redirect(url_for("overtime"))

    employees = get_employees(status="all")
    requests = get_overtime_requests()
    return render_template("overtime.html", user_name=session.get("user_name", "User"), employees=employees, requests=requests)


@app.route("/friday-overtime", methods=["GET", "POST"])
def friday_overtime():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action in {"approve", "reject"} and not user_has_role("admin", "manager"):
            flash("ليس لديك صلاحية اعتماد أو رفض إضافي الجمعة.", "error")
            return redirect(url_for("friday_overtime"))

        if action == "create_friday":
            employee_id = request.form.get("employee_id")
            if employee_id:
                record_id = add_friday_overtime(
                    int(employee_id),
                    request.form.get("friday_date"),
                    request.form.get("start_time"),
                    request.form.get("end_time"),
                    session.get("user_name", "system"),
                )
                if record_id:
                    flash("تم تسجيل إضافي الجمعة بنجاح.", "success")
                else:
                    flash("تأكد من بيانات يوم الجمعة.", "error")
        elif action == "approve":
            record_id = request.form.get("record_id")
            if record_id:
                with __import__('database').get_connection() as conn:
                    conn.execute("UPDATE friday_overtime SET status = ?, approved_by = ?, approved_at = ? WHERE id = ?", ("approved", session.get("user_name", "system"), datetime.today().strftime("%Y-%m-%d %H:%M:%S"), int(record_id)))
                    conn.commit()
                flash("تم اعتماد إضافي الجمعة.", "success")
        elif action == "reject":
            record_id = request.form.get("record_id")
            if record_id:
                with __import__('database').get_connection() as conn:
                    conn.execute("UPDATE friday_overtime SET status = ?, approved_by = ?, approved_at = ? WHERE id = ?", ("rejected", session.get("user_name", "system"), datetime.today().strftime("%Y-%m-%d %H:%M:%S"), int(record_id)))
                    conn.commit()
                flash("تم رفض إضافي الجمعة.", "success")
        return redirect(url_for("friday_overtime"))

    employees = get_employees(status="all")
    requests = get_friday_overtime()
    return render_template("friday_overtime.html", user_name=session.get("user_name", "User"), employees=employees, requests=requests)


@app.route("/holiday-overtime", methods=["GET", "POST"])
def holiday_overtime():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        action = request.form.get("action")
        if action in {"approve", "reject"} and not user_has_role("admin", "manager"):
            flash("ليس لديك صلاحية اعتماد أو رفض إضافي العطل.", "error")
            return redirect(url_for("holiday_overtime"))

        if action == "create_holiday":
            employee_id = request.form.get("employee_id")
            if employee_id:
                record_id = add_holiday_overtime(
                    int(employee_id),
                    request.form.get("holiday_name", "العطلة الرسمية"),
                    request.form.get("work_date"),
                    float(request.form.get("total_hours", 0) or 0),
                    float(request.form.get("multiplier", 2.5) or 2.5),
                    session.get("user_name", "system"),
                )
                if record_id:
                    flash("تم تسجيل إضافي العطلة الرسمية بنجاح.", "success")
                else:
                    flash("يرجى مراجعة بيانات العطلة.", "error")
        elif action == "approve":
            record_id = request.form.get("record_id")
            if record_id:
                with __import__('database').get_connection() as conn:
                    conn.execute("UPDATE holiday_overtime SET status = ?, approved_by = ?, approved_at = ? WHERE id = ?", ("approved", session.get("user_name", "system"), datetime.today().strftime("%Y-%m-%d %H:%M:%S"), int(record_id)))
                    conn.commit()
                flash("تم اعتماد إضافي العطلة.", "success")
        elif action == "reject":
            record_id = request.form.get("record_id")
            if record_id:
                with __import__('database').get_connection() as conn:
                    conn.execute("UPDATE holiday_overtime SET status = ?, approved_by = ?, approved_at = ? WHERE id = ?", ("rejected", session.get("user_name", "system"), datetime.today().strftime("%Y-%m-%d %H:%M:%S"), int(record_id)))
                    conn.commit()
                flash("تم رفض إضافي العطلة.", "success")
        return redirect(url_for("holiday_overtime"))

    employees = get_employees(status="all")
    requests = get_holiday_overtime()
    return render_template("holiday_overtime.html", user_name=session.get("user_name", "User"), employees=employees, requests=requests)


@app.route("/payslip/<int:employee_id>")
def payslip(employee_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    month = request.args.get("month") or datetime.today().strftime("%Y-%m")
    employee = get_employee_by_id(employee_id)
    if not employee:
        flash("الموظف غير موجود.", "error")
        return redirect(url_for("payroll"))

    payroll_record = next((row for row in get_payroll_records(month) if row["employee_id"] == employee_id), None)
    if payroll_record is None:
        payroll_record = {
            "basic_salary": employee.get("base_salary") or 0,
            "late_deduction": 0,
            "regular_overtime": 0,
            "friday_overtime": 0,
            "holiday_overtime": 0,
            "net_salary": employee.get("base_salary") or 0,
            "late_minutes": 0,
            "period_month": month,
            "status": "draft",
        }
    late_summary = get_employee_late_summary(employee_id, month)
    settings = get_salary_settings(employee_id)
    return render_template(
        "payslip.html",
        user_name=session.get("user_name", "User"),
        employee=employee,
        payroll_record=payroll_record,
        month=month,
        late_summary=late_summary,
        settings=settings,
    )


@app.route("/payroll", methods=["GET", "POST"])
def payroll():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        employee_id = request.form.get("employee_id")
        month = request.form.get("month") or datetime.today().strftime("%Y-%m")
        if employee_id:
            employee = get_employee_by_id(employee_id)
            if employee:
                amount = float(employee.get("base_salary", 0) or 0)
                adjustment_total = 0.0
                discount_total = 0.0
                for row in get_monthly_report(month, employee_id):
                    adjustment_total = float(row.get("adjustment_total", 0) or 0)
                    discount_total = float(row.get("discount_total", 0) or 0)
                total = amount + adjustment_total - discount_total
                add_payroll_payout(employee_id, month, total, "paid", "صرف راتب شهري")
                flash("تم صرف راتب الموظف بنجاح.", "success")
            else:
                flash("الموظف غير موجود.", "error")
        else:
            flash("يرجى اختيار موظف.", "error")
        return redirect(url_for("payroll"))

    selected_month = request.args.get("month") or datetime.today().strftime("%Y-%m")
    payouts = get_payroll_payouts(selected_month)
    payroll_records = get_payroll_records(selected_month)
    payroll_map = {int(row["employee_id"]): row for row in payroll_records}

    items = []
    for emp in get_employees():
        record = payroll_map.get(int(emp["id"]))
        base_salary = float(emp.get("base_salary", 0) or 0)
        net_salary = float(record.get("net_salary", base_salary) or base_salary) if record else base_salary
        paid = any(item["employee_id"] == emp["id"] and item["month"] == selected_month for item in payouts)
        items.append({
            "employee": emp,
            "amount": net_salary,
            "paid": paid,
            "record": record,
        })

    total_basic = sum(float(item["employee"].get("base_salary", 0) or 0) for item in items)
    total_net = sum(float(item["amount"]) for item in items)
    total_overtime = sum(
        float((item.get("record") or {}).get("regular_overtime", 0) or 0) +
        float((item.get("record") or {}).get("friday_overtime", 0) or 0) +
        float((item.get("record") or {}).get("holiday_overtime", 0) or 0)
        for item in items
    )
    total_deductions = sum(float((item.get("record") or {}).get("total_deductions", 0) or 0) for item in items)
    total_paid = sum(float(pay.get("amount", 0) or 0) for pay in payouts if pay.get("status") == "paid")
    employees_with_data = len([item for item in items if item.get("record")])

    analytics = {
        "total_basic": total_basic,
        "total_overtime": total_overtime,
        "total_deductions": total_deductions,
        "total_net": total_net,
        "total_paid": total_paid,
        "average_net": total_net / len(items) if items else 0,
        "employees_with_data": employees_with_data,
    }

    payroll_chart_data = {
        "labels": ["الراتب الأساسي", "المكافآت", "الخصومات", "صافي الراتب"],
        "datasets": [{
            "data": [
                round(total_basic, 2),
                round(total_overtime, 2),
                round(total_deductions, 2),
                round(total_net, 2),
            ],
            "backgroundColor": ["#8b5e3c", "#d7b58a", "#c5654b", "#6ea86b"],
        }],
    }

    salary_distribution = {
        "labels": [item["employee"]["full_name"] for item in items[:8]],
        "values": [float(item["amount"]) for item in items[:8]],
    }

    return render_template(
        "payroll.html",
        user_name=session.get("user_name", "User"),
        items=items,
        selected_month=selected_month,
        payouts=payouts,
        analytics=analytics,
        payroll_chart_data=payroll_chart_data,
        salary_distribution=salary_distribution,
    )


@app.route("/report_excel", methods=["POST"])
def report_excel():
    if "user_id" not in session:
        return redirect(url_for("login"))

    month = request.form.get("month") or datetime.today().strftime("%Y-%m")
    employee_id = request.form.get("employee_id")
    rows = get_monthly_report(month, employee_id) if employee_id else get_monthly_report(month)

    wb = Workbook()
    ws = wb.active
    ws.title = "HR_Report"
    headers = ["Employee", "Role", "Base Salary", "Adjustments", "Discounts", "Present", "Absent", "Late", "Leave Days", "Total"]
    ws.append(headers)
    for row in rows:
        ws.append([
            row["full_name"],
            row["role"],
            float(row["base_salary"]),
            float(row["adjustment_total"]),
            float(row["discount_total"]),
            int(row["present_days"]),
            int(row["absent_days"]),
            int(row["late_days"]),
            int(row["leave_days"]),
            float(row["total_salary"]),
        ])

    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            value = cell.value
            if value is not None:
                max_length = max(max_length, len(str(value)))
        ws.column_dimensions[column_letter].width = max_length + 2

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"hr_report_{month}.xlsx"
    return Response(
        buffer.getvalue(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/report_pdf", methods=["POST"])
def report_pdf():
    if "user_id" not in session:
        return redirect(url_for("login"))

    month = request.form.get("month") or datetime.today().strftime("%Y-%m")
    employee_id = request.form.get("employee_id")
    rows = get_monthly_report(month, employee_id) if employee_id else get_monthly_report(month)

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []
    title = Paragraph(f"Rahiq Pharmacy HR Invoice Report - {month}", styles["Title"])
    subtitle = Paragraph("Payroll & Attendance Summary", styles["Heading2"])
    elements.append(title)
    elements.append(subtitle)
    elements.append(Spacer(1, 14))

    table_data = [["Employee", "Role", "Salary", "Adjustments", "Discounts", "Present", "Absent", "Late", "Leave", "Total"]]
    for row in rows:
        table_data.append([
            row["full_name"],
            row["role"],
            f"{row['base_salary']:.2f} LYD",
            f"{row['adjustment_total']:.2f} LYD",
            f"{row['discount_total']:.2f} LYD",
            str(row["present_days"]),
            str(row["absent_days"]),
            str(row["late_days"]),
            str(row["leave_days"]),
            f"{row['total_salary']:.2f} LYD",
        ])

    table = Table(table_data)
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d7a4d")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 1, colors.grey),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    elements.append(table)
    elements.append(Spacer(1, 18))
    total_amount = sum(float(row["total_salary"]) for row in rows)
    elements.append(Paragraph(f"Total Amount: {total_amount:.2f} LYD", styles["Heading2"]))
    doc.build(elements)

    pdf = buffer.getvalue()
    buffer.close()
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename=hr_report_{month}.pdf"})


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(__import__("os").environ.get("PORT", "5007")))
