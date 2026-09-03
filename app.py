from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import requests
import math
import datetime
from passlib.hash import pbkdf2_sha512
from jose import JWTError, jwt
from conf import create_jwt_token, verify_jwt_token
# add firebase
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
app.secret_key = '8888'  # Replace with a secure secret key

# Initialize Firebase instead of MySQL
cred = credentials.Certificate("/etc/secrets/serviceAccountKey.json")  # path to your downloaded JSON
firebase_admin.initialize_app(cred)

db = firestore.client()

# Azure Maps subscription key
subscription_key = '29tQsOgaggLiWIY5lVfJ9pQ4MabgWEyAIcJSNCrUfEP1f33W6NDjJQQJ99AGACYeBjFd4FboAAAgAZMPZYdR'

def calculate_distance(start_lat, start_lon, end_lat, end_lon):
    url = "https://atlas.microsoft.com/route/directions/json"
    query = f'{start_lat},{start_lon}:{end_lat},{end_lon}'
    params = {
        'api-version': '1.0',
        'subscription-key': subscription_key,
        'query': query,
        'routingMode': 'car',
        'instructionsType': 'text'
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        data = response.json()
        if 'routes' in data and len(data['routes']) > 0:
            route = data['routes'][0]
            distance_meters = route['summary']['lengthInMeters']
            distance_km = distance_meters / 1000
            return round(distance_km, 2)
        else:
            return 0
    else:
        return 0

def get_place_name(latitude, longitude):
    url = f"https://atlas.microsoft.com/search/address/reverse/json?api-version=1.0&query={latitude},{longitude}&subscription-key={subscription_key}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['addresses']:
            return data['addresses'][0]['address']['freeformAddress']
    return "Unknown Location"

def is_logged_in():
    return 'username' in session   # ✅ unified

def login_required(f):
    def wrapped(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapped.__name__ = f.__name__
    return wrapped

def get_attendance_status(username):
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    docs = db.collection('hr_attendance') \
             .where('employee_id', '==', username) \
             .where('date', '==', today) \
             .stream()
    for doc in docs:
        row = doc.to_dict()
        if row.get('check_in') and not row.get('check_out'):
            return "IN", doc.id
        elif row.get('check_in') and row.get('check_out'):
            return "OUT", doc.id
    return "NONE", None

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        users_ref = db.collection('res_users')
        query = users_ref.where('login', '==', username).where('active', '==', True).stream()

        user = None
        for doc in query:
            user = doc.to_dict()
            user['id'] = doc.id

        if user and pbkdf2_sha512.verify(password, user['password']):
            session['username'] = user['id']   # ✅ unified
            session['token'] = create_jwt_token(str(user['id']))
            return redirect(url_for('attendance'))
        else:
            flash("Invalid username or password. Please try again.")
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        users_ref = db.collection('res_users')
        user_doc = users_ref.document(username).get()

        if user_doc.exists:
            flash("Username already exists. Please try a different one.")
        else:
            hashed_password = pbkdf2_sha512.hash(password)
            db.collection('res_users').document(username).set({
                'login': username,
                'password': hashed_password,
                'active': True
            })
            db.collection('hr_employee').document(username).set({
                'name': username,
                'user_id': username
            })
            flash("Signup successful! Please log in.")
            return redirect(url_for('login'))

    return render_template('signup.html')

@app.route('/generate_token', methods=['POST'])
def generate_token():
    user_id = session.get('username')   # ✅ unified
    if user_id:
        token = create_jwt_token(str(user_id))
        return jsonify({'token': token})
    else:
        return jsonify({'error': 'User not logged in'}), 401

@app.route('/logout', methods=['GET', 'POST'])
def logout():
    session.pop('username', None)   # ✅ unified
    session.pop('token', None)
    flash("You have been logged out.")
    return redirect(url_for('login'))

@app.route('/redirect_login')
def redirect_login():
    token = request.args.get('token')
    if token:
        try:
            user_id = verify_jwt_token(token)
            if user_id:
                session['username'] = user_id['user_id']   # ✅ unified
                session['token'] = token
                return redirect(url_for('index'))
            else:
                flash("Invalid token. Please log in again.")
                return redirect(url_for('login'))
        except JWTError:
            flash("Invalid token. Please log in again.")
            return redirect(url_for('login'))
    else:
        flash("Token missing. Please log in.")
        return redirect(url_for('login'))

@app.route('/user-info', methods=['GET'])
def user_info():
    if 'username' in session:   #  unified
        user_id = session['username']
        user_doc = db.collection('res_users').document(user_id).get()
        if user_doc.exists:
            user = user_doc.to_dict()
            return jsonify({
                'isLoggedIn': True,
                'username': user.get('login')
            })
        else:
            return jsonify({'isLoggedIn': False, 'username': None})
    else:
        return jsonify({'isLoggedIn': False, 'username': None})

@app.route("/")
def index():
    if 'username' in session:   # unified
        return render_template('index.html', coordinates=[], route_geometry=[], start_lat=None, start_lon=None)
    return render_template('index.html', coordinates=[], route_geometry=[], start_lat=None, start_lon=None)

@app.route('/tracking_id/<tracking_id>', methods=['GET'])
def get_route(tracking_id):
    # Query Firestore for route entries
    docs = db.collection('route_tracking_entry') \
             .where('tracking_id', '==', tracking_id) \
             .order_by('time') \
             .stream()
 
    result = [doc.to_dict() for doc in docs]
 
    coordinates = []
    previous_point = None
    total_distance = 0
 
    for row in result:
        latitude = row.get('latitude')
        longitude = row.get('longitude')
        time_val = row.get('time')
 
        # Format time for UI
        time_str = None
        if time_val:
            if isinstance(time_val, datetime.datetime):
               time_str = time_val.strftime('%Y-%m-%d %H:%M:%S')
            else:
                time_str = str(time_val)

 
        # Calculate distance from previous point
        if previous_point:
            prev_lat, prev_lon = previous_point['latitude'], previous_point['longitude']
            distance = calculate_distance(prev_lat, prev_lon, latitude, longitude)
            total_distance += distance
        else:
            distance = 0
 
        # Reverse geocode place name
        place_name = get_place_name(latitude, longitude)
 
        coordinates.append({
            'latitude': latitude,
            'longitude': longitude,
            'time': time_str,
            'place_name': place_name,
            'distance_from_previous': distance
        })
 
        previous_point = {'latitude': latitude, 'longitude': longitude}
 
    # Starting point for zoom
    start_lat = coordinates[0]['latitude'] if coordinates else None
    start_lon = coordinates[0]['longitude'] if coordinates else None
 
    # Build Azure Maps query
    if len(coordinates) >= 2:
        query = ":".join([f"{coord['latitude']},{coord['longitude']}" for coord in coordinates])
        route_url = f"https://atlas.microsoft.com/route/directions/json?api-version=1.0&query={query}&routeType=shortest"
 
        route_response = requests.get(route_url, headers={'Subscription-Key': subscription_key})
        route_data = route_response.json()
 
        route_geometry = []
        if route_data.get('routes'):
            for leg in route_data['routes'][0]['legs']:
                for point in leg['points']:
                    route_geometry.append([point['longitude'], point['latitude']])
    else:
        route_geometry = []
 
    return render_template(
        'index.html',
        coordinates=coordinates,
        route_geometry=route_geometry,
        start_lat=start_lat,
        start_lon=start_lon
    )
@app.route('/attendance', methods=['GET', 'POST'])
@login_required
def attendance():
    # Get the selected date from the request, or use the current date by default
    selected_date = request.form.get('date')
    if not selected_date:
        selected_date = datetime.datetime.now().strftime('%Y-%m-%d')

    # Query Firestore for attendance records on that date
    attendance_docs = db.collection('hr_attendance') \
                        .where('date', '==', selected_date) \
                        .stream()

    check_in_pointers = []
    check_out_pointers = []
    total_employees = set()
    checked_in_employees = 0
    checked_out_employees = 0

    for doc in attendance_docs:
        row = doc.to_dict()

        employee_id = row.get('employee_id')
        check_in = row.get('check_in')
        check_out = row.get('check_out')
        check_in_lat = row.get('check_in_latitude')
        check_in_lon = row.get('check_in_longitude')
        check_out_lat = row.get('check_out_latitude')
        check_out_lon = row.get('check_out_longitude')
        check_in_place = row.get('check_in_place')
        check_out_place = row.get('check_out_place')
        check_in_time = row.get('check_in_time')
        check_out_time = row.get('check_out_time')

        # Fetch employee name from hr_employee collection
        emp_doc = db.collection('hr_employee').document(employee_id).get()
        employee_name = emp_doc.to_dict().get('name') if emp_doc.exists else "Unknown"

        total_employees.add(employee_name)

        if check_in and check_in_lat and check_in_lon:
            checked_in_employees += 1
            check_in_pointers.append({
                'employee_name': employee_name,
                'latitude': check_in_lat,
                'longitude': check_in_lon,
                'time': check_in_time if check_in_time else check_in,
                'place_name': check_in_place if check_in_place else "Unknown"
            })

        if check_out and check_out_lat and check_out_lon:
            checked_out_employees += 1
            check_out_pointers.append({
                'employee_name': employee_name,
                'latitude': check_out_lat,
                'longitude': check_out_lon,
                'time': check_out_time if check_out_time else check_out,
                'place_name': check_out_place if check_out_place else "Unknown"
            })

    side_screen_data = {
        'total_employees': len(total_employees),
        'checked_in_employees': checked_in_employees,
        'checked_out_employees': checked_out_employees
    }
    #  Add these lines before render_template
    username = session.get('username')
    status, _ = get_attendance_status(username)

    return render_template(
        'attendance.html',
        check_in_pointers=check_in_pointers,
        check_out_pointers=check_out_pointers,
        side_screen_data=side_screen_data,
        selected_date=selected_date,
        status=status, # now defined 
        subscription_key=subscription_key
        

    )
@app.route('/toggle_punch', methods=['POST'])
@login_required
def toggle_punch():
    username = session.get('username')
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    now = datetime.datetime.now().strftime('%H:%M:%S')

    # Values coming from the hidden inputs in your form
    lat = request.form.get('lat')
    lon = request.form.get('lon')
    place_name = request.form.get('place_name')
    punch_time = request.form.get('time')

    # Fetch employee record to get consistent user_id and name
    emp_doc = db.collection('hr_employee').document(username).get()
    if emp_doc.exists:
        emp_data = emp_doc.to_dict()
        employee_id = emp_data.get('user_id', username)
        employee_name = emp_data.get('name', username)
    else:
        employee_id = username
        employee_name = username

    # Check current status (NONE → Punch In, IN → Punch Out)
    status, _ = get_attendance_status(employee_id)

    if status == "NONE":
        # Punch In → create new record with employee_id as document ID
        db.collection('hr_attendance').document(employee_id).set({
            'employee_id': employee_id,
            'employee_name': employee_name,
            'date': today,
            'check_in': now,
            'check_in_latitude': lat,
            'check_in_longitude': lon,
            'check_in_place': place_name,
            'check_in_time': punch_time
        })

    elif status == "IN":
        # Punch Out → update the same record
        db.collection('hr_attendance').document(employee_id).update({
            'check_out': now,
            'check_out_latitude': lat,
            'check_out_longitude': lon,
            'check_out_place': place_name,
            'check_out_time': punch_time,
            'employee_name': employee_name
        })

    return redirect(url_for('attendance'))


 
@app.route('/visit', methods=['GET', 'POST'])
@login_required
def visit():
    # Handle the date filter
    if request.method == 'POST' and request.form.get('date'):
       selected_date = request.form.get('date')
    else:
       selected_date = datetime.date.today().isoformat()

 
    # Query Firestore for visits on the selected date
    visit_docs = db.collection('kalai_visit') \
                   .where('date', '==', selected_date) \
                   .stream()
 
    visit_points = []
    for doc in visit_docs:
        row = doc.to_dict()
 
        start_lat = row.get('latitude')
        start_lon = row.get('longitude')
        end_lat = row.get('end_latitude')
        end_lon = row.get('end_longitude')
        start_time = row.get('start_time')
        end_time = row.get('end_time')
        assigned_to = row.get('assigned_to')
        start_place_name = row.get('start_location')
        end_place_name = row.get('end_location')
        name = row.get('name')
 
        # Fetch employee name from res_users collection
        emp_doc = db.collection('res_users').document(assigned_to).get()
        employee_name = emp_doc.to_dict().get('login') if emp_doc.exists else "Unknown"
 
        # Calculate distance and place names
        distance = calculate_distance(start_lat, start_lon, end_lat, end_lon) if (start_lat and start_lon and end_lat and end_lon) else 0
        start_place_name = get_place_name(start_lat, start_lon) if (start_lat and start_lon) else None
        end_place_name = get_place_name(end_lat, end_lon) if (end_lat and end_lon) else None
 
        visit_points.append({
            'name': name,
            'start_latitude': start_lat,
            'start_longitude': start_lon,
            'end_latitude': end_lat,
            'end_longitude': end_lon,
            'start_time': start_time,
            'end_time': end_time,
            'employee_name': employee_name,
            'start_place_name': start_place_name,
            'end_place_name': end_place_name,
            'distance': distance
        })
 
    # Totals
    total_visits = len(visit_points)
    active_visits = sum(1 for visit in visit_points if visit['end_latitude'] is None or visit['end_longitude'] is None)
    completed_visits = total_visits - active_visits
 
    return render_template(
        'visit.html',
        visit_points=visit_points,
        selected_date=selected_date,
        total_visits=total_visits,
        active_visits=active_visits,
        completed_visits=completed_visits
    )



if __name__ == '__main__':
    app.run(debug=True)


