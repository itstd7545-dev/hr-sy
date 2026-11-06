import unittest

from app import app
from database import add_employee, get_employee_status_history


class HrAppTests(unittest.TestCase):
    def test_dashboard_redirects_when_logged_out(self):
        client = app.test_client()
        response = client.get('/dashboard')
        self.assertEqual(response.status_code, 302)

    def test_leave_management_route_exists(self):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_name'] = 'Admin'
            sess['user_role'] = 'admin'

        response = client.get('/leaves')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'\xd8\xa5\xd8\xaf\xd8\xa7\xd8\xb1\xd8\xa9 \xd8\xa7\xd9\x84\xd8\xa5\xd8\xac\xd8\xa7\xd8\xb2\xd8\xa7\xd8\xaa', response.data)

    def test_register_accepts_role_selection(self):
        client = app.test_client()
        response = client.post('/register', data={
            'full_name': 'Tester User',
            'email': 'tester@example.com',
            'password': 'secret123',
            'confirm_password': 'secret123',
            'role': 'admin',
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

    def test_developer_tools_route_exists(self):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_name'] = 'Designer'
            sess['user_role'] = 'system_designer'

        response = client.get('/developer-tools')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Version', response.data)

    def test_maintenance_mode_blocks_login(self):
        original = app.config.get('MAINTENANCE_MODE')
        app.config['MAINTENANCE_MODE'] = True
        try:
            client = app.test_client()
            response = client.post('/login', data={
                'email': 'admin@example.com',
                'password': 'wrongpass',
            }, follow_redirects=True)
            text = response.get_data(as_text=True)
            self.assertIn('الصيانة', text)
            self.assertIn('تسجيل الدخول', text)
        finally:
            app.config['MAINTENANCE_MODE'] = original

    def test_employee_status_history_records_reason(self):
        employee_id = add_employee(
            'Status Tester',
            'Accountant',
            '0550000000',
            1200,
            8,
            '2024-01-01',
            'active',
            'full_time',
            'Initial record',
            '08:00',
            '17:00',
        )

        from database import update_employee
        update_employee(str(employee_id), {
            'full_name': 'Status Tester',
            'role': 'Accountant',
            'phone': '0550000000',
            'base_salary': 1200,
            'work_hours': 8,
            'hire_date': '2024-01-01',
            'status': 'suspended',
            'employment_type': 'full_time',
            'notes': 'Updated status',
            'check_in_time': '08:00',
            'check_out_time': '17:00',
            'reason': 'فترة تجريبية منتهية',
        })

        history = get_employee_status_history(employee_id)
        self.assertTrue(any(item['new_status'] == 'suspended' and item['reason'] == 'فترة تجريبية منتهية' for item in history))

    def test_recruitment_and_offboarding_routes_exist(self):
        client = app.test_client()
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['user_name'] = 'Admin'
            sess['user_role'] = 'admin'

        recruitment = client.post('/recruitment', data={
            'position_title': 'Senior HR Officer',
            'department': 'HR',
            'manager': 'Noura',
            'vacancies': '2',
            'requirements': 'Bachelor + 3 years',
            'status': 'new',
            'action': 'create_request',
        }, follow_redirects=False)
        self.assertIn(recruitment.status_code, (200, 302))

        offboarding = client.post('/offboarding', data={
            'employee_id': '1',
            'departure_type': 'resignation',
            'reason': 'Career move',
            'request_date': '2026-11-06',
            'last_work_day': '2026-11-20',
            'assigned_to': 'HR Manager',
            'action': 'create_request',
        }, follow_redirects=False)
        self.assertIn(offboarding.status_code, (200, 302))

    def test_login_rejects_wrong_selected_role(self):
        client = app.test_client()
        response = client.post('/register', data={
            'full_name': 'Designer User',
            'email': 'designer@example.com',
            'password': 'secret123',
            'confirm_password': 'secret123',
            'role': 'system_designer',
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)

        login_response = client.post('/login', data={
            'email': 'designer@example.com',
            'password': 'secret123',
            'role': 'hr',
        }, follow_redirects=True)
        self.assertIn('الصلاحية', login_response.get_data(as_text=True))
        self.assertNotIn('لوحة تحكم', login_response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
