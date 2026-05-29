import os
import json
import uuid
import bcrypt
import jwt
import smtplib
import zipfile
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps
from email.message import EmailMessage
from bson import ObjectId
from django.http import JsonResponse, HttpResponse, FileResponse, HttpResponseNotAllowed
from django.views.decorators.csrf import csrf_exempt
from .mongo import db
from .email_utils import send_password_reset_code, send_verification_code

JWT_SECRET = os.getenv('JWT_SECRET', 'your_super_secret_key')
ADMIN_MASTER_PASSWORD = os.getenv('ADMIN_MASTER_PASSWORD', 'novaadmin123')


def parse_json_body(request):
    try:
        body = request.body.decode('utf-8')
        if not body:
            return {}
        return json.loads(body)
    except Exception:
        return {}


def serialize_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: serialize_value(v) for k, v in value.items()}
    return value


def json_response(data=None, status=200):
    if data is None:
        return JsonResponse({}, status=status)
    safe = not isinstance(data, list)
    return JsonResponse(serialize_value(data), safe=safe, status=status)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))


def get_bearer_token(request):
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        return auth_header.split(' ', 1)[1]
    return None


def generate_jwt(payload):
    payload_copy = payload.copy()
    payload_copy['exp'] = datetime.utcnow() + timedelta(hours=24)
    token = jwt.encode(payload_copy, JWT_SECRET, algorithm='HS256')
    if isinstance(token, bytes):
        return token.decode('utf-8')
    return token


def decode_jwt(token):
    return jwt.decode(token, JWT_SECRET, algorithms=['HS256'])


def jwt_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        token = get_bearer_token(request)
        if not token:
            return json_response({'error': 'Authorization token missing'}, status=401)
        try:
            payload = decode_jwt(token)
            request.user = payload
        except jwt.ExpiredSignatureError:
            return json_response({'error': 'Token expired'}, status=403)
        except jwt.InvalidTokenError:
            return json_response({'error': 'Invalid token'}, status=403)
        return view_func(request, *args, **kwargs)
    return wrapper


def role_required(roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            auth_response = jwt_required(lambda req, *a, **k: None)(request, *args, **kwargs)
            if isinstance(auth_response, HttpResponse) and auth_response.status_code != 200:
                return auth_response
            role = getattr(request, 'user', {}).get('role')
            if role not in roles:
                return json_response({'message': 'Access denied'}, status=403)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def convert_to_object_id(id_str):
    """Convert string ID to ObjectId, handling both ObjectId strings and plain strings"""
    if not id_str:
        return None
    if isinstance(id_str, ObjectId):
        return id_str
    try:
        # Try to parse as ObjectId if it looks like one (24 hex chars)
        if isinstance(id_str, str) and len(id_str) == 24 and all(c in '0123456789abcdef' for c in id_str.lower()):
            return ObjectId(id_str)
        # Otherwise return as-is (for UUIDs and other string IDs)
        return id_str
    except Exception:
        return id_str


def get_user_by_id(user_id):
    user_id_obj = convert_to_object_id(user_id)
    if user_id_obj is None:
        return None
    return db.users.find_one({'_id': user_id_obj})


def get_employee_by_user_id(user_id):
    return db.employees.find_one({'userId': user_id})


def get_user_name(user):
    if not user:
        return 'Unknown'
    first = user.get('firstName')
    last = user.get('lastName')
    if first and last:
        return f'{first} {last}'.strip()
    if first:
        return first
    return user.get('email', '').split('@')[0]


def get_employee_name(employee, user):
    if employee and employee.get('firstName'):
        return f"{employee.get('firstName')} {employee.get('lastName', '')}".strip()
    return get_user_name(user)



def create_base_response(doc):
    if not doc:
        return None
    doc['id'] = doc.get('_id')
    return doc


def send_admin_otp(email):
    otp_code = f'{uuid.uuid4().int % 900000 + 100000}'
    expiry = datetime.utcnow() + timedelta(minutes=10)
    db.users.update_one({'email': email}, {'$set': {'verificationCode': otp_code, 'resetCodeExpiry': expiry, 'updatedAt': datetime.utcnow()}})
    send_verification_code(email, otp_code)


@csrf_exempt
def register_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    data = parse_json_body(request)
    email = data.get('email')
    password = data.get('password')
    role = data.get('role')
    first_name = data.get('firstName')
    last_name = data.get('lastName')
    employee_id = data.get('employeeId')
    phone = data.get('phone', '')

    if not email or not password or not role or not first_name or not last_name or not employee_id:
        return json_response({'error': 'Missing required registration fields'}, status=400)

    existing_by_email = db.users.find_one({'email': email})
    existing_by_employee_id = db.users.find_one({'employeeId': employee_id})

    if existing_by_email and not existing_by_email.get('isVerified', False):
        new_code = f'{uuid.uuid4().int % 900000 + 100000}'
        db.users.update_one({ '_id': existing_by_email['_id'] }, { '$set': { 'verificationCode': new_code, 'updatedAt': datetime.utcnow() } })
        send_verification_code(email, new_code)
        return json_response({
            'message': 'A new verification code has been sent to your email. Please verify to activate your account.',
            'email': email,
            'resent': True
        })

    if existing_by_email or existing_by_employee_id:
        field = 'Email' if existing_by_email else 'Employee ID'
        return json_response({'error': f'{field} already registered'}, status=400)

    if role in ['Admin', 'HR']:
        role_count = db.users.count_documents({'role': role})
        if role_count >= 1:
            return json_response({'error': f'An {role} already exists. Only one {role} is allowed.'}, status=400)

    verification_code = f'{uuid.uuid4().int % 900000 + 100000}'
    user_id = str(uuid.uuid4())
    user_doc = {
        '_id': user_id,
        'firstName': first_name,
        'lastName': last_name,
        'email': email,
        'employeeId': employee_id,
        'password': hash_password(password),
        'role': role,
        'isVerified': False,
        'verificationCode': verification_code,
        'resetCodeExpiry': None,
        'createdAt': datetime.utcnow(),
        'updatedAt': datetime.utcnow(),
    }
    db.users.insert_one(user_doc)

    if role in ['Employee', 'Teamlead', 'HR']:
        employee_doc = {
            '_id': str(uuid.uuid4()),
            'userId': user_id,
            'firstName': first_name,
            'lastName': last_name,
            'phone': phone,
            'profileImage': '',
            'address': '',
            'designation': '',
            'department': '',
            'baseSalary': 0,
            'bonus': 0,
            'deductions': 0,
            'netSalary': 0,
            'joiningDate': '',
            'status': 'Active',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        }
        db.employees.insert_one(employee_doc)

    send_verification_code(email, verification_code)
    return json_response({'message': 'User registered successfully. Please check your email for the 6-digit verification code.', 'email': email}, status=201)


@csrf_exempt
def verify_code_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    email = data.get('email')
    code = data.get('code')
    user = db.users.find_one({'email': email, 'verificationCode': code})
    if not user:
        return json_response({'error': 'Invalid verification code'}, status=400)
    db.users.update_one({'_id': user['_id']}, {'$set': {'isVerified': True, 'verificationCode': None, 'updatedAt': datetime.utcnow()}})
    return json_response({'message': 'Email verified successfully. You can now login.'})


@csrf_exempt
def forgot_password_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    email = data.get('email')
    user = db.users.find_one({'email': email})
    if user:
        reset_code = f'{uuid.uuid4().int % 900000 + 100000}'
        reset_expiry = datetime.utcnow() + timedelta(minutes=10)
        db.users.update_one({'_id': user['_id']}, {'$set': {'verificationCode': reset_code, 'resetCodeExpiry': reset_expiry, 'updatedAt': datetime.utcnow()}})
        send_password_reset_code(email, reset_code)
    return json_response({'message': 'If that email is registered, a password reset code has been sent.'})


@csrf_exempt
def verify_reset_code_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    email = data.get('email')
    code = data.get('code')
    user = db.users.find_one({'email': email, 'verificationCode': code})
    if not user:
        return json_response({'error': 'Invalid or expired reset code.'}, status=400)
    expiry = user.get('resetCodeExpiry')
    if expiry and datetime.utcnow() > expiry:
        return json_response({'error': 'Reset code has expired. Please request a new one.'}, status=400)
    return json_response({'message': 'Code verified. You may now reset your password.', 'valid': True})


@csrf_exempt
def reset_password_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    email = data.get('email')
    code = data.get('code')
    password = data.get('password')
    user = db.users.find_one({'email': email, 'verificationCode': code})
    if not user:
        return json_response({'error': 'Invalid or expired reset code.'}, status=400)
    expiry = user.get('resetCodeExpiry')
    if expiry and datetime.utcnow() > expiry:
        return json_response({'error': 'Reset code has expired. Please request a new one.'}, status=400)
    db.users.update_one({'_id': user['_id']}, {'$set': {'password': hash_password(password), 'verificationCode': None, 'resetCodeExpiry': None, 'updatedAt': datetime.utcnow()}})
    return json_response({'message': 'Password reset successfully. You can now login with your new password.'})


@csrf_exempt
def login_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    email = data.get('email')
    password = data.get('password')
    user = db.users.find_one({'email': email})
    if not user:
        return json_response({'error': 'No account found with this email address.'}, status=401)
    if not check_password(password, user['password']):
        return json_response({'error': 'Incorrect password. Please try again.'}, status=401)
    if not user.get('isVerified', False):
        new_code = f'{uuid.uuid4().int % 900000 + 100000}'
        db.users.update_one({'_id': user['_id']}, {'$set': {'verificationCode': new_code, 'updatedAt': datetime.utcnow()}})
        send_verification_code(email, new_code)
        return json_response({'error': 'Your email is not verified. A new verification code has been sent to your email.', 'needsVerification': True, 'email': email}, status=403)
    if user.get('role') == 'Admin':
        send_admin_otp(email)
        return json_response({'otpRequired': True, 'message': 'Admin OTP sent to your email.'})
    employee = get_employee_by_user_id(user['_id'])
    token = generate_jwt({'id': user['_id'], 'role': user['role']})
    return json_response({'token': token, 'user': {'id': user['_id'], 'email': user['email'], 'role': user['role'], 'firstName': user.get('firstName', employee.get('firstName') if employee else 'N/A'), 'lastName': user.get('lastName', employee.get('lastName') if employee else 'N/A')}})


@csrf_exempt
def verify_master_password_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    password = data.get('password')
    if password != ADMIN_MASTER_PASSWORD:
        return json_response({'error': 'Incorrect Master Password.'}, status=401)
    return json_response({'valid': True, 'message': 'Password accepted'})


@csrf_exempt
def admin_login_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    email = data.get('email')
    password = data.get('password')
    if password != ADMIN_MASTER_PASSWORD:
        return json_response({'error': 'Incorrect Master Password. Please try again.'}, status=401)
    user = db.users.find_one({'email': email})
    if user and user.get('role') != 'Admin':
        return json_response({'error': 'This email is already registered as an Employee. Please use a different email for Admin.'}, status=403)
    if not user:
        user_id = str(uuid.uuid4())
        user = {
            '_id': user_id,
            'firstName': 'Admin',
            'lastName': 'User',
            'email': email,
            'employeeId': f'ADMIN-{int(datetime.utcnow().timestamp())}',
            'password': hash_password(uuid.uuid4().hex),
            'role': 'Admin',
            'isVerified': True,
            'verificationCode': None,
            'resetCodeExpiry': None,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        }
        db.users.insert_one(user)
        user = db.users.find_one({'_id': user_id})
    send_admin_otp(email)
    return json_response({'otpRequired': True, 'message': 'Master Password accepted. Admin OTP sent to your email.'})


@csrf_exempt
def verify_admin_otp_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    email = data.get('email')
    code = data.get('code')
    user = db.users.find_one({'email': email, 'verificationCode': code, 'role': 'Admin'})
    if not user:
        return json_response({'error': 'Invalid or expired OTP code.'}, status=400)
    expiry = user.get('resetCodeExpiry')
    if expiry and datetime.utcnow() > expiry:
        return json_response({'error': 'OTP code has expired.'}, status=400)
    db.users.update_one({'_id': user['_id']}, {'$set': {'verificationCode': None, 'resetCodeExpiry': None, 'updatedAt': datetime.utcnow()}})
    token = generate_jwt({'id': user['_id'], 'role': user['role']})
    employee = get_employee_by_user_id(user['_id'])
    return json_response({'token': token, 'user': {'id': user['_uid'] if '_uid' in user else user['_id'], 'email': user['email'], 'role': user['role'], 'firstName': user.get('firstName', employee.get('firstName') if employee else 'N/A'), 'lastName': user.get('lastName', employee.get('lastName') if employee else 'N/A')}})


@csrf_exempt
@jwt_required
def switch_role_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    user_id_str = request.user.get('id')
    user_id = convert_to_object_id(user_id_str)
    if not user_id:
        return json_response({'error': 'Invalid user ID'}, status=400)
    user = db.users.find_one({'_id': user_id})
    if not user:
        return json_response({'error': 'User not found'}, status=404)
    current_role = user.get('role')
    if current_role not in ['Employee', 'Teamlead', 'HR']:
        return json_response({'error': 'Only Employees, Team Leads, and HR can switch roles.'}, status=400)
    new_role = 'Employee' if current_role == 'HR' else ('Teamlead' if current_role == 'Employee' else 'Employee')
    db.users.update_one({'_id': user_id}, {'$set': {'role': new_role, 'updatedAt': datetime.utcnow()}})
    employee = get_employee_by_user_id(user_id_str)
    token = generate_jwt({'id': user_id_str, 'role': new_role})
    return json_response({'message': f'Role switched to {new_role} successfully.', 'token': token, 'user': {'id': user_id_str, 'email': user['email'], 'role': new_role, 'firstName': user.get('firstName', employee.get('firstName') if employee else 'N/A'), 'lastName': user.get('lastName', employee.get('lastName') if employee else 'N/A')}})

@csrf_exempt
@jwt_required
def get_profile_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    user_id_str = request.user.get('id')
    user_id = convert_to_object_id(user_id_str)
    if not user_id:
        return json_response({'error': 'Invalid user ID'}, status=400)
    user = db.users.find_one({'_id': user_id}, {'password': 0, 'verificationCode': 0, 'resetCodeExpiry': 0})
    if not user:
        return json_response({'error': 'User not found'}, status=404)
    employee = get_employee_by_user_id(user_id_str)
    profile_data = {
        'id': user_id_str,
        'email': user['email'],
        'role': user.get('role'),
        'firstName': user.get('firstName', employee.get('firstName') if employee else 'N/A'),
        'lastName': user.get('lastName', employee.get('lastName') if employee else 'N/A'),
        'phone': employee.get('phone') if employee else 'N/A',
        'profileImage': employee.get('profileImage') if employee else None,
        'employeeId': user.get('employeeId', 'N/A'),
        'isVerified': user.get('isVerified', False),
        'createdAt': user.get('createdAt')
    }
    return json_response(profile_data)


@csrf_exempt
@jwt_required
def update_profile_view(request):
    if request.method != 'PUT':
        return HttpResponseNotAllowed(['PUT'])
    data = parse_json_body(request)
    first_name = data.get('firstName')
    last_name = data.get('lastName')
    phone = data.get('phone', '')
    profile_image = data.get('profileImage', '')
    if not first_name or not last_name:
        return json_response({'error': 'First Name and Last Name are required'}, status=400)
    user_id_str = request.user.get('id')
    user_id = convert_to_object_id(user_id_str)
    if not user_id:
        return json_response({'error': 'Invalid user ID'}, status=400)
    db.users.update_one({'_id': user_id}, {'$set': {'firstName': first_name, 'lastName': last_name, 'updatedAt': datetime.utcnow()}})
    user = db.users.find_one({'_id': user_id})
    if user and user.get('role') in ['Employee', 'Teamlead', 'HR']:
        db.employees.update_one({'userId': user_id_str}, {'$set': {'firstName': first_name, 'lastName': last_name, 'phone': phone, 'profileImage': profile_image, 'updatedAt': datetime.utcnow()}}, upsert=True)
    employee = get_employee_by_user_id(user_id_str)
    profile_data = {
        'id': user_id_str,
        'email': user['email'],
        'role': user.get('role'),
        'firstName': user.get('firstName', employee.get('firstName') if employee else 'N/A'),
        'lastName': user.get('lastName', employee.get('lastName') if employee else 'N/A'),
        'phone': employee.get('phone') if employee else 'N/A',
        'profileImage': employee.get('profileImage') if employee else None,
        'employeeId': user.get('employeeId', 'N/A')
    }
    return json_response({'message': 'Profile updated successfully', 'user': profile_data})


@csrf_exempt
def resend_verification_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    email = data.get('email')
    if not email:
        return json_response({'error': 'Email is required.'}, status=400)
    user = db.users.find_one({'email': email})
    if not user:
        return json_response({'message': 'If this email is registered, a verification code has been sent.'})
    if user.get('isVerified', False):
        return json_response({'message': 'Your account is already verified. Please login.'})
    new_code = f'{uuid.uuid4().int % 900000 + 100000}'
    db.users.update_one({'_id': user['_id']}, {'$set': {'verificationCode': new_code, 'updatedAt': datetime.utcnow()}})
    send_verification_code(email, new_code)
    return json_response({'message': 'A new verification code has been sent to your email.'})


@csrf_exempt
@jwt_required
def submit_leave_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    data = parse_json_body(request)
    leave_type = data.get('leaveType')
    from_date = data.get('fromDate')
    to_date = data.get('toDate')
    reason = data.get('reason')
    user_id = request.user.get('id')
    if not leave_type or not from_date or not to_date or not reason:
        return json_response({'error': 'All fields are required'}, status=400)
    try:
        from_dt = datetime.fromisoformat(from_date)
        to_dt = datetime.fromisoformat(to_date)
    except Exception:
        return json_response({'error': 'Invalid date format'}, status=400)
    if to_dt < from_dt:
        return json_response({'error': 'To date must be after From date'}, status=400)
    days = (to_dt.date() - from_dt.date()).days + 1
    user = get_user_by_id(user_id)
    employee = get_employee_by_user_id(user_id)
    leave_doc = {
        '_id': str(uuid.uuid4()),
        'userId': user_id,
        'employeeName': get_employee_name(employee, user),
        'employeeEmail': user.get('email'),
        'leaveType': leave_type,
        'fromDate': from_dt,
        'toDate': to_dt,
        'days': days,
        'reason': reason,
        'status': 'Pending',
        'hrComment': None,
        'createdAt': datetime.utcnow(),
        'updatedAt': datetime.utcnow(),
    }
    db.leaves.insert_one(leave_doc)
    return json_response({'message': 'Leave request submitted successfully', 'leave': create_base_response(leave_doc)}, status=201)


@csrf_exempt
@jwt_required
def get_my_leaves_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    user_id = request.user.get('id')
    leaves = list(db.leaves.find({'userId': user_id}).sort('createdAt', -1))
    for leave in leaves:
        leave['id'] = leave['_id']
    return json_response(leaves)


@csrf_exempt
@jwt_required
def get_all_leaves_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    role = request.user.get('role')
    query = {}
    if role == 'HR':
        non_hr_users = list(db.users.find({'role': {'$ne': 'HR'}}, {'_id': 1}))
        non_hr_ids = [user['_id'] for user in non_hr_users]
        query['userId'] = {'$in': non_hr_ids}
    leaves = list(db.leaves.find(query).sort('createdAt', -1))
    user_ids = list({leave['userId'] for leave in leaves})
    user_map = {user['_id']: user for user in db.users.find({'_id': {'$in': user_ids}}, {'role': 1})}
    result = []
    for leave in leaves:
        leave['id'] = leave['_id']
        if leave.get('userId') in user_map:
            leave['User'] = {'role': user_map[leave['userId']]['role']}
        result.append(leave)
    return json_response(result)


@csrf_exempt
@jwt_required
def update_leave_status_view(request, leave_id):
    if request.method != 'PATCH':
        return HttpResponseNotAllowed(['PATCH'])
    data = parse_json_body(request)
    status = data.get('status')
    hr_comment = data.get('hrComment', '')
    current_role = request.user.get('role')
    if status not in ['Approved', 'Rejected']:
        return json_response({'error': 'Status must be Approved or Rejected'}, status=400)
    leave = db.leaves.find_one({'_id': leave_id})
    if not leave:
        return json_response({'error': 'Leave request not found'}, status=404)
    user_for_leave = get_user_by_id(leave['userId'])
    if current_role == 'HR' and user_for_leave and user_for_leave.get('role') == 'HR':
        return json_response({'error': 'HR employees cannot approve or reject leaves for other HR staff. This must be done by an Admin.'}, status=403)
    db.leaves.update_one({'_id': leave_id}, {'$set': {'status': status, 'hrComment': hr_comment, 'updatedAt': datetime.utcnow()}})
    leave['status'] = status
    leave['hrComment'] = hr_comment
    return json_response({'message': f'Leave request {status.lower()} successfully', 'leave': create_base_response(leave)})


@csrf_exempt
@jwt_required
def get_leave_balance_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    user_id = request.user.get('id')
    allowances = {'Annual Leave': 18, 'Sick Leave': 10, 'Casual Leave': 7}
    pipeline = [
        {'$match': {'userId': user_id, 'status': 'Approved'}},
        {'$group': {'_id': '$leaveType', 'totalUsed': {'$sum': '$days'}}}
    ]
    used_leaves = list(db.leaves.aggregate(pipeline))
    used_map = {item['_id']: int(item['totalUsed']) for item in used_leaves}
    balances = []
    for leave_type, total in allowances.items():
        used = used_map.get(leave_type, 0)
        balances.append({'type': leave_type, 'total': total, 'used': used, 'available': total - used})
    return json_response(balances)


@csrf_exempt
@jwt_required
@role_required(['Teamlead', 'Admin', 'HR'])
def get_all_employees_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    users = list(db.users.find({'role': {'$in': ['Employee', 'Teamlead', 'HR']}}, {'email': 1, 'role': 1, 'firstName': 1, 'lastName': 1}))
    user_ids = [user['_id'] for user in users]
    profiles = list(db.employees.find({'userId': {'$in': user_ids}}))
    profile_map = {profile['userId']: profile for profile in profiles}
    result = []
    for user in users:
        profile = profile_map.get(user['_id'], {})
        result.append({
            'id': user['_id'],
            'email': user['email'],
            'name': f"{profile.get('firstName') or user.get('firstName', '').strip()} {profile.get('lastName') or user.get('lastName', '')}".strip() or user['email'].split('@')[0],
            'designation': profile.get('designation') or user.get('role')
        })
    return json_response(result)


@csrf_exempt
@jwt_required
@role_required(['Teamlead'])
def projects_view(request):
    if request.method == 'POST':
        data = parse_json_body(request)
        name = data.get('name')
        description = data.get('description')
        deadline = data.get('deadline')
        employee_ids = data.get('employeeIds', [])
        team_lead_id = request.user.get('id')
        if not name or not description or not employee_ids:
            return json_response({'error': 'Project name, description, and at least one employee are required.'}, status=400)
        lead = get_user_by_id(team_lead_id)
        lead_profile = get_employee_by_user_id(team_lead_id)
        team_lead_name = get_employee_name(lead_profile, lead)
        deadline_dt = None
        if deadline:
            try:
                deadline_dt = datetime.fromisoformat(deadline)
            except Exception:
                deadline_dt = None
        project_doc = {
            '_id': str(uuid.uuid4()),
            'teamLeadId': team_lead_id,
            'teamLeadName': team_lead_name,
            'name': name,
            'description': description,
            'deadline': deadline_dt,
            'status': 'Active',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        }
        db.projects.insert_one(project_doc)
        employees = list(db.users.find({'_id': {'$in': employee_ids}}))
        profiles = list(db.employees.find({'userId': {'$in': employee_ids}}))
        profile_map = {profile['userId']: profile for profile in profiles}
        invitations = []
        for employee in employees:
            profile = profile_map.get(employee['_id'], {})
            invitations.append({
                '_id': str(uuid.uuid4()),
                'projectId': project_doc['_id'],
                'teamLeadId': team_lead_id,
                'employeeId': employee['_id'],
                'employeeName': get_employee_name(profile, employee),
                'employeeEmail': employee['email'],
                'status': 'Pending',
                'createdAt': datetime.utcnow(),
                'updatedAt': datetime.utcnow(),
            })
        if invitations:
            db.teaminvitations.insert_many(invitations)
        return json_response({'message': 'Project created and invitations sent.', 'project': create_base_response(project_doc)}, status=201)

    if request.method == 'GET':
        projects = list(db.projects.find({'teamLeadId': request.user.get('id')}).sort('createdAt', -1))
        project_ids = [project['_id'] for project in projects]
        invitations = list(db.teaminvitations.find({'projectId': {'$in': project_ids}}))
        ideas = list(db.projectideas.find({'projectId': {'$in': project_ids}}))
        result = []
        for project in projects:
            project['id'] = project['_id']
            project_invitations = [dict(inv, id=inv['_id']) for inv in invitations if inv['projectId'] == project['_id']]
            project_ideas = [dict(idea, id=idea['_id']) for idea in ideas if idea['projectId'] == project['_id']]
            project['TeamInvitations'] = project_invitations
            project['ProjectIdeas'] = project_ideas
            result.append(project)
        return json_response(result)

    return HttpResponseNotAllowed(['GET', 'POST'])


@csrf_exempt
@jwt_required
@role_required(['Employee'])
def invitations_view(request):
    if request.method == 'GET':
        invitations = list(db.teaminvitations.find({'employeeId': request.user.get('id')}).sort('createdAt', -1))
        project_ids = [inv['projectId'] for inv in invitations if inv.get('projectId')]
        projects = {project['_id']: project for project in db.projects.find({'_id': {'$in': project_ids}})}
        ideas = list(db.projectideas.find({'projectId': {'$in': project_ids}}))
        result = []
        for inv in invitations:
            project = projects.get(inv['projectId'])
            if project:
                project_data = dict(project, id=project['_id'])
                project_data['ProjectIdeas'] = [dict(i, id=i['_id']) for i in ideas if i['projectId'] == project['_id']]
                inv['Project'] = project_data
            inv['id'] = inv['_id']
            result.append(inv)
        return json_response(result)
    return HttpResponseNotAllowed(['GET'])


@csrf_exempt
@jwt_required
@role_required(['Employee'])
def respond_to_invitation_view(request, invitation_id):
    if request.method != 'PATCH':
        return HttpResponseNotAllowed(['PATCH'])
    data = parse_json_body(request)
    status = data.get('status')
    if status not in ['Accepted', 'Rejected']:
        return json_response({'error': 'Status must be Accepted or Rejected'}, status=400)
    invitation = db.teaminvitations.find_one({'_id': invitation_id, 'employeeId': request.user.get('id')})
    if not invitation:
        return json_response({'error': 'Invitation not found'}, status=404)
    if invitation.get('status') != 'Pending':
        return json_response({'error': 'Invitation already responded to'}, status=400)
    db.teaminvitations.update_one({'_id': invitation_id}, {'$set': {'status': status, 'updatedAt': datetime.utcnow()}})
    invitation['status'] = status
    return json_response({'message': f'Invitation {status.lower()} successfully.', 'invitation': create_base_response(invitation)})


@csrf_exempt
@jwt_required
def project_ideas_view(request, project_id):
    if request.method == 'POST':
        data = parse_json_body(request)
        idea_text = data.get('idea')
        if not idea_text or not idea_text.strip():
            return json_response({'error': 'Idea cannot be empty'}, status=400)
        project = db.projects.find_one({'_id': project_id})
        if not project:
            return json_response({'error': 'Project not found'}, status=404)
        author_id = request.user.get('id')
        is_team_lead = project.get('teamLeadId') == author_id
        is_member = db.teaminvitations.find_one({'projectId': project_id, 'employeeId': author_id, 'status': 'Accepted'})
        if not is_team_lead and not is_member:
            return json_response({'error': 'You are not a member of this project'}, status=403)
        author = get_user_by_id(author_id)
        author_profile = get_employee_by_user_id(author_id)
        idea_doc = {
            '_id': str(uuid.uuid4()),
            'projectId': project_id,
            'authorId': author_id,
            'authorName': get_employee_name(author_profile, author),
            'authorRole': request.user.get('role'),
            'idea': idea_text.strip(),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        }
        db.projectideas.insert_one(idea_doc)
        return json_response(create_base_response(idea_doc), status=201)
    if request.method == 'GET':
        ideas = list(db.projectideas.find({'projectId': project_id}).sort('createdAt', -1))
        for idea in ideas:
            idea['id'] = idea['_id']
        return json_response(ideas)
    return HttpResponseNotAllowed(['GET', 'POST'])


@csrf_exempt
@jwt_required
def check_in_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    user_id = request.user.get('id')
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    existing = db.attendance.find_one({'userId': user_id, 'date': today})
    if existing:
        return json_response({'error': 'Already checked in today'}, status=400)
    attendance = {
        '_id': str(uuid.uuid4()),
        'userId': user_id,
        'date': today,
        'checkIn': datetime.utcnow(),
        'checkOut': None,
        'hoursWorked': 0,
        'status': 'Present',
        'createdAt': datetime.utcnow(),
        'updatedAt': datetime.utcnow(),
    }
    db.attendance.insert_one(attendance)
    return json_response({'message': 'Checked in successfully', 'attendance': create_base_response(attendance)}, status=201)


@csrf_exempt
@jwt_required
def check_out_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    user_id = request.user.get('id')
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    attendance = db.attendance.find_one({'userId': user_id, 'date': today})
    if not attendance:
        return json_response({'error': 'Check-in record not found for today'}, status=404)
    if attendance.get('checkOut') is not None:
        return json_response({'error': 'Already checked out today'}, status=400)
    check_out_time = datetime.utcnow()
    diff_hours = round((check_out_time - attendance['checkIn']).total_seconds() / 3600, 2)
    db.attendance.update_one({'_id': attendance['_id']}, {'$set': {'checkOut': check_out_time, 'hoursWorked': diff_hours, 'updatedAt': datetime.utcnow()}})
    attendance['checkOut'] = check_out_time
    attendance['hoursWorked'] = diff_hours
    return json_response({'message': 'Checked out successfully', 'attendance': create_base_response(attendance)})


@csrf_exempt
@jwt_required
def get_my_attendance_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    user_id = request.user.get('id')
    attendance = list(db.attendance.find({'userId': user_id}).sort('date', -1))
    for record in attendance:
        record['id'] = record['_id']
    return json_response(attendance)


@csrf_exempt
@jwt_required
def get_all_attendance_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    if request.user.get('role') not in ['Admin', 'HR']:
        return json_response({'error': 'Access denied'}, status=403)
    attendance = list(db.attendance.find().sort('date', -1))
    user_ids = list({record['userId'] for record in attendance})
    users = {user['_id']: user for user in db.users.find({'_id': {'$in': user_ids}}, {'email': 1, 'role': 1, 'firstName': 1, 'lastName': 1})}
    for record in attendance:
        record['id'] = record['_id']
        user = users.get(record['userId'])
        if user:
            record['User'] = {'email': user['email'], 'role': user['role'], 'firstName': user.get('firstName'), 'lastName': user.get('lastName')}
        else:
            record['User'] = {'email': 'Unknown User', 'role': 'N/A', 'firstName': 'Unknown', 'lastName': 'N/A'}
    return json_response(attendance)


@csrf_exempt
@jwt_required
def get_today_status_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    user_id = request.user.get('id')
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    attendance = db.attendance.find_one({'userId': user_id, 'date': today})
    if not attendance:
        return json_response({'message': 'Not checked in'})
    attendance['id'] = attendance['_id']
    return json_response(attendance)


@csrf_exempt
@jwt_required
def circulars_view(request):
    if request.method == 'GET':
        circulars = list(db.circulars.find().sort([('date', -1), ('createdAt', -1)]))
        for circ in circulars:
            circ['id'] = circ['_id']
        return json_response(circulars)
    if request.method == 'POST':
        data = parse_json_body(request)
        if request.user.get('role') not in ['Admin', 'HR']:
            return json_response({'error': 'Access denied'}, status=403)
        title = data.get('title')
        content = data.get('content')
        circular_type = data.get('type', 'Info')
        date_value = data.get('date')
        if not title or not content or not date_value:
            return json_response({'error': 'Title, content and date are required'}, status=400)
        try:
            date_obj = datetime.fromisoformat(date_value)
        except Exception:
            return json_response({'error': 'Invalid date format'}, status=400)
        circular_doc = {
            '_id': str(uuid.uuid4()),
            'title': title,
            'content': content,
            'type': circular_type,
            'date': date_obj,
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        }
        db.circulars.insert_one(circular_doc)
        return json_response({'message': 'Circular posted successfully', 'circular': create_base_response(circular_doc)}, status=201)
    return HttpResponseNotAllowed(['GET', 'POST'])


@csrf_exempt
@jwt_required
def circular_detail_view(request, circular_id):
    if request.method != 'DELETE':
        return HttpResponseNotAllowed(['DELETE'])
    if request.user.get('role') not in ['Admin', 'HR']:
        return json_response({'error': 'Access denied'}, status=403)
    circular = db.circulars.find_one({'_id': circular_id})
    if not circular:
        return json_response({'error': 'Circular not found'}, status=404)
    db.circulars.delete_one({'_id': circular_id})
    return json_response({'message': 'Circular deleted successfully'})


@csrf_exempt
@jwt_required
def get_stats_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    role = request.user.get('role')
    user_id = request.user.get('id')
    today = datetime.utcnow().date()
    first_of_month = today.replace(day=1)
    if role == 'Employee':
        tasks_pending = db.tasks.count_documents({'userId': user_id, 'status': {'$ne': 'Completed'}})
        tasks_due_today = db.tasks.count_documents({'userId': user_id, 'status': {'$ne': 'Completed'}, 'due': {'$gte': datetime.combine(today, datetime.min.time()), '$lt': datetime.combine(today + timedelta(days=1), datetime.min.time())}})
        pipeline = [
            {'$match': {'userId': user_id, 'status': 'Approved'}},
            {'$group': {'_id': '$leaveType', 'totalUsed': {'$sum': '$days'}}}
        ]
        approved_leaves = list(db.leaves.aggregate(pipeline))
        used_days = sum(int(item['totalUsed']) for item in approved_leaves)
        leave_balance = 35 - used_days
        days_present = db.attendance.count_documents({'userId': user_id, 'date': {'$gte': datetime.combine(first_of_month, datetime.min.time()), '$lt': datetime.combine(today + timedelta(days=1), datetime.min.time())}, 'status': 'Present'})
        total_tasks = db.tasks.count_documents({'userId': user_id})
        completed_tasks = db.tasks.count_documents({'userId': user_id, 'status': 'Completed'})
        performance_score = round((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0
        return json_response({'tasksPending': tasks_pending, 'tasksDueToday': tasks_due_today, 'leaveBalance': leave_balance, 'daysPresent': days_present, 'performance': f'{performance_score}%'});
    total_employees = db.users.count_documents({'role': 'Employee'})
    pending_leaves = db.leaves.count_documents({'status': 'Pending'})
    active_projects = db.projects.count_documents({})
    today_count = db.attendance.count_documents({'date': {'$gte': datetime.combine(today, datetime.min.time()), '$lt': datetime.combine(today + timedelta(days=1), datetime.min.time())}, 'status': 'Present'})
    attendance_rate = round((today_count / total_employees) * 100) if total_employees > 0 else 0
    return json_response({'totalEmployees': total_employees, 'pendingLeaves': pending_leaves, 'activeProjects': active_projects, 'attendanceRate': f'{attendance_rate}%'});


@csrf_exempt
@jwt_required
def get_my_tasks_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    tasks = list(db.tasks.find({'userId': request.user.get('id')}).sort('due', 1))
    for task in tasks:
        task['id'] = task['_id']
    return json_response(tasks)


@csrf_exempt
@jwt_required
def get_assigned_tasks_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    tasks = list(db.tasks.find({'createdBy': request.user.get('id')}).sort('createdAt', -1))
    user_ids = list({task['userId'] for task in tasks if task.get('userId')})
    profiles = {profile['userId']: profile for profile in db.employees.find({'userId': {'$in': user_ids}})}
    users = {user['_id']: user for user in db.users.find({'_id': {'$in': user_ids}}, {'email': 1, 'role': 1, 'firstName': 1, 'lastName': 1})}
    for task in tasks:
        task['id'] = task['_id']
        user = users.get(task['userId'])
        if user:
            profile = profiles.get(task['userId'], {})
            task['User'] = {'email': user['email'], 'role': user['role'], 'firstName': profile.get('firstName') or user.get('firstName'), 'lastName': profile.get('lastName') or user.get('lastName'), 'Employee': {'firstName': profile.get('firstName'), 'lastName': profile.get('lastName')} if profile else None}
    return json_response(tasks)


@csrf_exempt
@jwt_required
def task_crud_view(request):
    if request.method == 'POST':
        data = parse_json_body(request)
        title = data.get('title')
        priority = data.get('priority')
        status = data.get('status')
        due = data.get('due')
        project = data.get('project', 'General')
        assigned_to = data.get('assignedTo') or request.user.get('id')
        if not title or not due:
            return json_response({'error': 'Title and due date are required'}, status=400)
        assigned_user = db.users.find_one({'_id': assigned_to})
        if assigned_user and assigned_user.get('role') == 'HR' and request.user.get('role') != 'Admin':
            return json_response({'error': 'Only Admins can assign tasks to employees with the HR role.'}, status=403)
        due_dt = None
        try:
            due_dt = datetime.fromisoformat(due)
        except Exception:
            return json_response({'error': 'Invalid due date format'}, status=400)
        task_doc = {
            '_id': str(uuid.uuid4()),
            'title': title,
            'priority': priority or 'Medium',
            'status': status or 'Pending',
            'due': due_dt,
            'project': project,
            'userId': assigned_to,
            'createdBy': request.user.get('id'),
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
        }
        db.tasks.insert_one(task_doc)
        return json_response(create_base_response(task_doc), status=201)
    return HttpResponseNotAllowed(['POST'])


@csrf_exempt
@jwt_required
def update_task_view(request, task_id):
    if request.method != 'PATCH':
        return HttpResponseNotAllowed(['PATCH'])
    data = parse_json_body(request)
    status = data.get('status')
    task = db.tasks.find_one({'_id': task_id})
    if not task:
        return json_response({'error': 'Task not found'}, status=404)
    user_id = request.user.get('id')
    is_assigned = task.get('userId') == user_id
    is_creator = task.get('createdBy') == user_id
    is_admin_hr = request.user.get('role') in ['Admin', 'HR']
    if not is_assigned and not is_creator and not is_admin_hr:
        return json_response({'error': 'You are not authorized to update this task.'}, status=403)
    db.tasks.update_one({'_id': task_id}, {'$set': {'status': status, 'updatedAt': datetime.utcnow()}})
    task['status'] = status
    return json_response(create_base_response(task))


@csrf_exempt
@jwt_required
@role_required(['Admin', 'HR'])
def get_all_performance_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    employees = list(db.users.find({'role': {'$in': ['Employee', 'Teamlead']}}, {'email': 1, 'firstName': 1, 'lastName': 1}))
    user_ids = [employee['_id'] for employee in employees]
    profiles = {profile['userId']: profile for profile in db.employees.find({'userId': {'$in': user_ids}})}
    today = datetime.utcnow().date()
    first_of_month = today.replace(day=1)
    result = []
    for user in employees:
        user_id = user['_id']
        total_tasks = db.tasks.count_documents({'userId': user_id})
        completed_tasks = db.tasks.count_documents({'userId': user_id, 'status': 'Completed'})
        task_accuracy = round((completed_tasks / total_tasks) * 100) if total_tasks > 0 else 0
        days_present = db.attendance.count_documents({'userId': user_id, 'date': {'$gte': datetime.combine(first_of_month, datetime.min.time()), '$lt': datetime.combine(today + timedelta(days=1), datetime.min.time())}, 'status': 'Present'})
        attendance_rate = min(100, round((days_present / 22) * 100))
        leave_agg = list(db.leaves.aggregate([{'$match': {'userId': user_id, 'status': 'Approved'}}, {'$group': {'_id': None, 'totalDays': {'$sum': '$days'}}}]))
        leave_days = leave_agg[0]['totalDays'] if leave_agg else 0
        profile = profiles.get(user_id, {})
        name = get_employee_name(profile, user)
        result.append({
            'id': user_id,
            'name': name,
            'email': user['email'],
            'designation': profile.get('designation', 'N/A'),
            'department': profile.get('department', 'N/A'),
            'metrics': {'taskAccuracy': task_accuracy, 'attendanceRate': attendance_rate, 'leaveDays': leave_days},
            'score': round((task_accuracy * 0.7) + (attendance_rate * 0.3))
        })
    result.sort(key=lambda item: item['score'], reverse=True)
    return json_response(result)


@csrf_exempt
@jwt_required
@role_required(['Admin', 'HR'])
def get_employees_with_salaries_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    employees = list(db.employees.find().sort('firstName', 1))
    user_ids = [emp['userId'] for emp in employees if emp.get('userId')]
    users = {user['_id']: user for user in db.users.find({'_id': {'$in': user_ids}}, {'email': 1, 'role': 1, 'employeeId': 1})}
    for emp in employees:
        emp['id'] = emp['_id']
        user = users.get(emp['userId'])
        emp['User'] = {'email': user.get('email', 'N/A') if user else 'N/A', 'role': user.get('role', 'N/A') if user else 'N/A', 'employeeId': user.get('employeeId', 'N/A') if user else 'N/A'}
    return json_response(employees)


@csrf_exempt
@jwt_required
@role_required(['Admin', 'HR'])
def update_salary_view(request, employee_id):
    if request.method != 'PUT':
        return HttpResponseNotAllowed(['PUT'])
    data = parse_json_body(request)
    base_salary = float(data.get('baseSalary', 0) or 0)
    bonus = float(data.get('bonus', 0) or 0)
    deductions = float(data.get('deductions', 0) or 0)
    employee = db.employees.find_one({'_id': employee_id})
    if not employee:
        return json_response({'error': 'Employee not found'}, status=404)
    net_salary = base_salary + bonus - deductions
    db.employees.update_one({'_id': employee_id}, {'$set': {'baseSalary': base_salary, 'bonus': bonus, 'deductions': deductions, 'netSalary': net_salary, 'updatedAt': datetime.utcnow()}})
    salary_doc = {
        '_id': str(uuid.uuid4()),
        'employeeId': employee_id,
        'basicSalary': base_salary,
        'bonus': bonus,
        'deductions': deductions,
        'netSalary': net_salary,
        'month': datetime.utcnow().strftime('%B'),
        'year': datetime.utcnow().year,
        'status': 'Paid',
        'createdAt': datetime.utcnow(),
        'updatedAt': datetime.utcnow(),
    }
    db.salaries.insert_one(salary_doc)
    employee['id'] = employee['_id']
    return json_response({'message': 'Salary updated and logged successfully', 'employee': employee})


@csrf_exempt
@jwt_required
def get_my_payslips_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    employee = get_employee_by_user_id(request.user.get('id'))
    if not employee:
        return json_response({'error': 'Employee profile not found'}, status=404)
    year = request.GET.get('year')
    month = request.GET.get('month')
    query = {'employeeId': employee['_id']}
    if year:
        query['year'] = int(year)
    if month:
        query['month'] = month
    payslips = list(db.salaries.find(query).sort([('year', -1), ('createdAt', -1)]))
    for slip in payslips:
        slip['id'] = slip['_id']
    return json_response(payslips)


def generate_payslip_pdf_bytes(salary, employee, user):
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setFont('Helvetica-Bold', 18)
    c.drawCentredString(300, 750, 'PAYSLIP')
    c.setFont('Helvetica', 10)
    c.drawCentredString(300, 735, 'Nova HamoTech - Employee Management System')
    c.line(50, 730, 550, 730)
    c.setFont('Helvetica-Bold', 12)
    c.drawString(60, 700, f'Employee Name: {employee.get("firstName", "")} {employee.get("lastName", "")}')
    c.drawString(60, 680, f'Employee ID: {user.get("employeeId", "N/A")}')
    c.drawString(60, 660, f'Department: {employee.get("department", "N/A")}')
    c.drawString(60, 640, f'Designation: {employee.get("designation", "N/A")}')
    c.drawString(60, 620, f'Period: {salary.get("month", "")} {salary.get("year", "")}')
    c.line(50, 610, 550, 610)
    c.setFont('Helvetica-Bold', 11)
    c.drawString(60, 590, 'Description')
    c.drawString(420, 590, 'Amount (INR)')
    c.setFont('Helvetica', 10)
    entries = [
        ('Basic Salary', salary.get('basicSalary', 0)),
        ('Bonus', salary.get('bonus', 0)),
        ('Deductions', -salary.get('deductions', 0)),
    ]
    y = 570
    for label, amount in entries:
        c.drawString(60, y, label)
        c.drawRightString(520, y, f'₹ {amount:,.2f}')
        y -= 20
    c.line(50, y, 550, y)
    y -= 20
    c.setFont('Helvetica-Bold', 12)
    c.drawString(60, y, 'Net Salary')
    c.drawRightString(520, y, f'₹ {salary.get("netSalary", 0):,.2f}')
    c.setFont('Helvetica', 9)
    c.drawString(60, 100, 'This is a computer-generated document and does not require a signature.')
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()


@csrf_exempt
@jwt_required
def download_payslip_view(request, salary_id):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    salary = db.salaries.find_one({'_id': salary_id})
    if not salary:
        return json_response({'error': 'Salary record not found'}, status=404)
    employee = db.employees.find_one({'_id': salary['employeeId']})
    if not employee or employee.get('userId') != request.user.get('id'):
        return json_response({'error': 'Unauthorized access to this payslip'}, status=403)
    user = get_user_by_id(request.user.get('id'))
    pdf_bytes = generate_payslip_pdf_bytes(salary, employee, user)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename=Payslip-{salary.get("month")}-{salary.get("year")}.pdf'
    return response


@csrf_exempt
@jwt_required
def download_yearly_payslips_view(request, year):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    employee = get_employee_by_user_id(request.user.get('id'))
    if not employee:
        return json_response({'error': 'Employee not found'}, status=404)
    user = get_user_by_id(request.user.get('id'))
    payslips = list(db.salaries.find({'employeeId': employee['_id'], 'year': year}))
    if not payslips:
        return json_response({'error': f'No payslips found for year {year}'}, status=404)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for slip in payslips:
            pdf_bytes = generate_payslip_pdf_bytes(slip, employee, user)
            filename = f'Payslip-{slip.get("month")}-{year}.pdf'
            archive.writestr(filename, pdf_bytes)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename=Payslips-{year}.zip'
    return response
from django.http import JsonResponse
import os

def test_email_config(request):
    return JsonResponse({
        "email_user_exists": bool(os.getenv("EMAIL_USER")),
        "email_pass_exists": bool(os.getenv("EMAIL_PASS"))
    })