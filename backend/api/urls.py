from django.urls import path
from . import views

urlpatterns = [
    path('auth/register', views.register_view),
    path('auth/login', views.login_view),
    path('auth/admin-login', views.admin_login_view),
    path('auth/verify-master-password', views.verify_master_password_view),
    path('auth/verify-code', views.verify_code_view),
    path('auth/forgot-password', views.forgot_password_view),
    path('auth/verify-reset-code', views.verify_reset_code_view),
    path('auth/reset-password', views.reset_password_view),
    path('auth/verify-admin-otp', views.verify_admin_otp_view),
    path('auth/resend-verification', views.resend_verification_view),
    path('auth/switch-role', views.switch_role_view),
    path('auth/profile', views.get_profile_view),
    path('auth/update-profile', views.update_profile_view),

    path('leaves/', views.submit_leave_view),
    path('leaves/my', views.get_my_leaves_view),
    path('leaves/balance', views.get_leave_balance_view),
    path('leaves/all', views.get_all_leaves_view),
    path('leaves/<str:leave_id>/status', views.update_leave_status_view),

    path('team/employees', views.get_all_employees_view),
    path('team/projects', views.projects_view),
    path('team/invitations', views.invitations_view),
    path('team/invitations/<str:invitation_id>', views.respond_to_invitation_view),
    path('team/projects/<str:project_id>/ideas', views.project_ideas_view),

    path('attendance/check-in', views.check_in_view),
    path('attendance/check-out', views.check_out_view),
    path('attendance/my', views.get_my_attendance_view),
    path('attendance/all', views.get_all_attendance_view),
    path('attendance/today', views.get_today_status_view),

    path('circulars/', views.circulars_view),
    path('circulars/<str:circular_id>', views.circular_detail_view),

    path('dashboard/stats', views.get_stats_view),

    path('tasks/my', views.get_my_tasks_view),
    path('tasks/assigned-by-me', views.get_assigned_tasks_view),
    path('tasks/', views.task_crud_view),
    path('tasks/<str:task_id>', views.update_task_view),

    path('performance/', views.get_all_performance_view),

    path('payroll/employees', views.get_employees_with_salaries_view),
    path('payroll/update-salary/<str:employee_id>', views.update_salary_view),

    path('payslips/my', views.get_my_payslips_view),
    path('payslips/download/<str:salary_id>', views.download_payslip_view),
    path('payslips/download-year/<int:year>', views.download_yearly_payslips_view),
]
