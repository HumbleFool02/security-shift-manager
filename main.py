import os
from datetime import date, datetime, timedelta
from functools import wraps

import jwt
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
from flask import Flask, render_template, redirect, url_for, request, g, abort, make_response, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

import pymysql
pymysql.install_as_MySQLdb()

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'mysql://root:@localhost/onlinesystem'
)
JWT_EXPIRY_HOURS = int(os.environ.get('JWT_EXPIRY_HOURS', 8))

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)

SHIFT_MORNING = 'Morning'
SHIFT_EVENING = 'Evening'
SHIFT_NIGHT = 'Night'
SHIFTS = [SHIFT_MORNING, SHIFT_EVENING, SHIFT_NIGHT]
SHIFT_TIMES = {
    SHIFT_MORNING: ('06:00', '14:00'),
    SHIFT_EVENING: ('14:00', '22:00'),
    SHIFT_NIGHT: ('22:00', '06:00'),
}

app.jinja_env.globals['SHIFTS'] = SHIFTS
app.jinja_env.globals['SHIFT_TIMES'] = SHIFT_TIMES


class Manager(db.Model):
    id = db.Column(db.Integer, unique=True)
    name = db.Column(db.String(120), unique=False, nullable=False)
    username = db.Column(db.String(120), unique=True, nullable=False)
    domain = db.Column(db.String(120), unique=False, nullable=False)
    idno = db.Column(db.String(120), primary_key=True, nullable=False)
    pword = db.Column(db.String(500), unique=False, nullable=False)

class Security(db.Model):
    id = db.Column(db.Integer, unique=True)
    name = db.Column(db.String(120), unique=False, nullable=False)
    username = db.Column(db.String(120), unique=True, nullable=False)
    domain = db.Column(db.String(120), unique=False, nullable=False)
    idno = db.Column(db.String(120), primary_key=True, nullable=False)
    pword = db.Column(db.String(120), unique=False, nullable=False)

class Absence(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    idno = db.Column(db.String(120), db.ForeignKey('security.idno'), nullable=False)
    sdate = db.Column(db.Date, nullable=False)
    edate = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(120), unique=False, nullable=False)
    status = db.Column(db.String(120), unique=False, nullable=False)
    timestamp = db.Column(db.DateTime, unique=False, nullable=False)

class Place(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=False, nullable=False)

class RosterBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='draft')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

class Duty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    didno = db.Column(db.String(120), db.ForeignKey('security.idno'), nullable=False)
    placeid = db.Column(db.Integer, db.ForeignKey('place.id'), nullable=False)
    ddate = db.Column(db.Date, nullable=False)
    shift = db.Column(db.String(20), nullable=False)
    is_overtime = db.Column(db.Boolean, nullable=False, default=False)
    batch_id = db.Column(db.Integer, db.ForeignKey('roster_batch.id'), nullable=True)

    place = db.relationship('Place', backref='duties')
    batch = db.relationship('RosterBatch', backref='duties')

    __table_args__ = (
        db.UniqueConstraint('didno', 'ddate', 'shift', name='uq_duty_person_date_shift'),
    )

class UncoveredSlot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('roster_batch.id'), nullable=False)
    placeid = db.Column(db.Integer, db.ForeignKey('place.id'), nullable=False)
    ddate = db.Column(db.Date, nullable=False)
    shift = db.Column(db.String(20), nullable=False)

    batch = db.relationship('RosterBatch', backref='uncovered_slots')
    place = db.relationship('Place')

class OvertimeRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    idno = db.Column(db.String(120), db.ForeignKey('security.idno'), nullable=False)
    ddate = db.Column(db.Date, nullable=False)
    shift = db.Column(db.String(20), nullable=False)
    placeid = db.Column(db.Integer, db.ForeignKey('place.id'), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Pending')
    timestamp = db.Column(db.DateTime, nullable=False)

    place = db.relationship('Place', backref='overtime_requests')


def parse_date(value):
    return datetime.strptime(value, '%Y-%m-%d').date()


def approved_leave_days_in_month(idno, year, month):
    month_start = date(year, month, 1)
    next_month = date(year + (month == 12), (month % 12) + 1, 1)
    month_end = next_month - timedelta(days=1)

    total_days = 0
    absences = Absence.query.filter_by(idno=idno, status='Approved').all()
    for a in absences:
        start = max(a.sdate, month_start)
        end = min(a.edate, month_end)
        if start <= end:
            total_days += (end - start).days + 1
    return total_days


def generate_token(idno, role):
    payload = {
        'idno': idno,
        'role': role,
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, app.secret_key, algorithm='HS256')


def token_required(role=None):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            token = request.cookies.get('token')
            if not token:
                return redirect(url_for('index'))
            try:
                payload = jwt.decode(token, app.secret_key, algorithms=['HS256'])
            except jwt.PyJWTError:
                return redirect(url_for('index'))
            if role and payload.get('role') != role:
                abort(403)
            g.user = {'idno': payload['idno'], 'role': payload['role']}
            return f(*args, **kwargs)
        return wrapped
    return decorator


def generate_roster(start_date, end_date):
    batch = RosterBatch(start_date=start_date, end_date=end_date, status='draft')
    db.session.add(batch)
    db.session.flush()

    places = Place.query.order_by(Place.id).all()
    persons = Security.query.order_by(Security.idno).all()

    leave_dates = {}
    for a in Absence.query.filter_by(status='Approved').all():
        if a.edate < start_date or a.sdate > end_date:
            continue
        d = max(a.sdate, start_date)
        last = min(a.edate, end_date)
        while d <= last:
            leave_dates.setdefault(a.idno, set()).add(d)
            d += timedelta(days=1)

    month_start = start_date.replace(day=1)
    counts = {p.idno: 0 for p in persons}
    committed = Duty.query.filter(
        Duty.is_overtime.is_(False),
        Duty.ddate >= month_start,
        Duty.ddate < start_date,
    ).all()
    for duty in committed:
        if duty.batch_id is None or (duty.batch and duty.batch.status == 'published'):
            counts[duty.didno] = counts.get(duty.didno, 0) + 1

    assigned_in_batch = {}
    existing_in_window = Duty.query.filter(Duty.ddate >= start_date, Duty.ddate <= end_date).all()
    for duty in existing_in_window:
        if duty.batch_id is None or (duty.batch and duty.batch.status == 'published'):
            assigned_in_batch.setdefault((duty.ddate, duty.shift), set()).add(duty.didno)

    d = start_date
    while d <= end_date:
        for shift in SHIFTS:
            key = (d, shift)
            for place in places:
                busy = assigned_in_batch.get(key, set())
                candidates = [
                    p for p in persons
                    if p.idno not in busy and d not in leave_dates.get(p.idno, set())
                ]
                if not candidates:
                    db.session.add(UncoveredSlot(batch_id=batch.id, placeid=place.id, ddate=d, shift=shift))
                    continue

                candidates.sort(key=lambda p: (counts.get(p.idno, 0), p.idno))
                chosen = candidates[0]

                db.session.add(Duty(
                    didno=chosen.idno, placeid=place.id, ddate=d, shift=shift,
                    is_overtime=False, batch_id=batch.id,
                ))
                counts[chosen.idno] = counts.get(chosen.idno, 0) + 1
                assigned_in_batch.setdefault(key, set()).add(chosen.idno)
        d += timedelta(days=1)

    db.session.commit()
    return batch


def render_manager_dashboard():
    manager = Manager.query.filter_by(idno=g.user['idno']).first()
    security = Security.query.filter_by(domain='Security').order_by(Security.name).all()
    pending_leaves = Absence.query.filter_by(status='Pending').order_by(Absence.timestamp).all()
    approved_leaves = Absence.query.filter_by(status='Approved').order_by(Absence.sdate).all()
    pending_overtime = OvertimeRequest.query.filter_by(status='Pending').order_by(OvertimeRequest.timestamp).all()
    duty = Duty.query.order_by(Duty.ddate).all()
    batches = RosterBatch.query.order_by(RosterBatch.start_date.desc()).all()

    today = date.today()
    leave_counts = {p.idno: approved_leave_days_in_month(p.idno, today.year, today.month) for p in security}

    return render_template(
        'managerdash.html', security=security, abes=pending_leaves,
        approved_leaves=approved_leaves,
        overtime_requests=pending_overtime, duty=duty, batches=batches,
        leave_counts=leave_counts, username=manager.username if manager else g.user['idno'],
    )


@app.route("/")
def home():
    return render_template('index.html')

@app.route("/index")
def index():
    return render_template('index.html')


@app.route("/ManagerLogin", methods=['GET', 'POST'])
def managerLogin():
    if request.method == 'GET':
        return render_template('ManagerLogin.html')

    username = request.form.get('username')
    pword = request.form.get('pword')
    data = Manager.query.filter_by(username=username).first()

    if data is not None and bcrypt.check_password_hash(data.pword, pword):
        token = generate_token(data.idno, 'Manager')
        resp = make_response(redirect(url_for('managerdash_view')))
        resp.set_cookie('token', token, httponly=True)
        return resp

    flash('Invalid username or password.', 'error')
    return redirect(url_for('managerLogin'))


@app.route("/managerdash")
@token_required(role='Manager')
def managerdash_view():
    return render_manager_dashboard()


@app.route("/SecurityLogin", methods=['GET', 'POST'])
def securityLogin():
    if request.method == 'GET':
        return render_template('SecurityLogin.html')

    username = request.form.get('username')
    pword = request.form.get('pword')
    data1 = Security.query.filter_by(username=username).first()

    if data1 is not None and bcrypt.check_password_hash(data1.pword, pword):
        token = generate_token(data1.idno, 'Security')
        resp = make_response(redirect(url_for('securitydashboard')))
        resp.set_cookie('token', token, httponly=True)
        return resp

    flash('Invalid username or password.', 'error')
    return redirect(url_for('securityLogin'))


@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for('index')))
    resp.set_cookie('token', '', expires=0)
    return resp


@app.route("/createduty", methods=['GET', 'POST'])
@token_required(role='Manager')
def createduty():
    if request.method == 'POST':
        didno = request.form.get('didno')
        ddate = parse_date(request.form.get('ddate'))
        shift = request.form.get('shift')

        try:
            placeid = int(request.form.get('placeid'))
        except (TypeError, ValueError):
            flash('Please provide a valid place number.', 'error')
            return redirect(url_for('createduty'))

        place = Place.query.get(placeid)
        if place is None:
            place = Place(id=placeid, name=f'Place {placeid}')
            db.session.add(place)

        db.session.add(Duty(didno=didno, ddate=ddate, shift=shift, placeid=placeid, is_overtime=False))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('That person already has a duty for that date and shift.', 'error')
            return redirect(url_for('createduty'))

        flash('Duty created.', 'success')
        return redirect(url_for('createduty'))

    return render_template("createduty.html")


@app.route("/securitydashboard", methods=['GET', 'POST'])
@token_required(role='Security')
def securitydashboard():
    if request.method == 'POST':
        sdate = parse_date(request.form.get('sdate'))
        edate = parse_date(request.form.get('edate'))
        reason = request.form.get('reason')

        overlap = Absence.query.filter(
            Absence.idno == g.user['idno'],
            Absence.status.in_(['Pending', 'Approved']),
            Absence.sdate <= edate,
            Absence.edate >= sdate,
        ).first()
        if overlap is not None:
            flash('This request overlaps one of your existing pending or approved leave requests.', 'error')
            return redirect(url_for('securitydashboard'))

        absence = Absence(
            idno=g.user['idno'], sdate=sdate, edate=edate, reason=reason,
            status='Pending', timestamp=datetime.utcnow(),
        )
        db.session.add(absence)
        db.session.commit()
        flash('Leave request submitted.', 'success')
        return redirect(url_for('securitydashboard'))

    today = date.today()
    week_end = today + timedelta(days=6)
    duty = Duty.query.filter(
        Duty.didno == g.user['idno'],
        Duty.ddate >= today,
        Duty.ddate <= week_end,
    ).all()
    duty = [d for d in duty if d.batch_id is None or (d.batch and d.batch.status == 'published')]
    duty.sort(key=lambda d: (d.ddate, SHIFTS.index(d.shift)))

    places = Place.query.order_by(Place.id).all()
    my_leaves = Absence.query.filter_by(idno=g.user['idno']).order_by(Absence.timestamp.desc()).all()
    my_overtime = OvertimeRequest.query.filter_by(idno=g.user['idno']).order_by(OvertimeRequest.timestamp.desc()).all()
    leave_days = approved_leave_days_in_month(g.user['idno'], today.year, today.month)

    return render_template(
        'securitydash.html', duty=duty, places=places,
        my_leaves=my_leaves, my_overtime=my_overtime, leave_days=leave_days,
    )


@app.route("/overtime-request", methods=['POST'])
@token_required(role='Security')
def overtime_request():
    ddate = parse_date(request.form.get('ddate'))
    shift = request.form.get('shift')

    try:
        placeid = int(request.form.get('placeid'))
    except (TypeError, ValueError):
        flash('Please provide a valid place number.', 'error')
        return redirect(url_for('securitydashboard'))

    db.session.add(OvertimeRequest(
        idno=g.user['idno'], ddate=ddate, shift=shift, placeid=placeid,
        status='Pending', timestamp=datetime.utcnow(),
    ))
    db.session.commit()
    return redirect(url_for('securitydashboard'))


@app.route("/manager/leave/<int:absence_id>/approve", methods=['POST'])
@token_required(role='Manager')
def approve_leave(absence_id):
    absence = Absence.query.get_or_404(absence_id)
    if absence.status != 'Pending':
        flash(f'This request has already been {absence.status.lower()}.', 'error')
        return redirect(url_for('managerdash_view'))
    absence.status = 'Approved'
    db.session.commit()
    flash('Leave request approved.', 'success')
    return redirect(url_for('managerdash_view'))


@app.route("/manager/leave/<int:absence_id>/decline", methods=['POST'])
@token_required(role='Manager')
def decline_leave(absence_id):
    absence = Absence.query.get_or_404(absence_id)
    if absence.status != 'Pending':
        flash(f'This request has already been {absence.status.lower()}.', 'error')
        return redirect(url_for('managerdash_view'))
    absence.status = 'Declined'
    db.session.commit()
    flash('Leave request declined.', 'success')
    return redirect(url_for('managerdash_view'))


@app.route("/manager/overtime/<int:req_id>/approve", methods=['POST'])
@token_required(role='Manager')
def approve_overtime(req_id):
    req = OvertimeRequest.query.get_or_404(req_id)
    if req.status != 'Pending':
        flash(f'This request has already been {req.status.lower()}.', 'error')
        return redirect(url_for('managerdash_view'))

    conflict = Duty.query.filter_by(didno=req.idno, ddate=req.ddate, shift=req.shift).first()
    if conflict is not None:
        req.status = 'Declined'
        db.session.commit()
        flash('Could not approve: that person already has a duty for that date and shift. Request declined.', 'error')
        return redirect(url_for('managerdash_view'))

    db.session.add(Duty(
        didno=req.idno, placeid=req.placeid, ddate=req.ddate, shift=req.shift,
        is_overtime=True,
    ))
    req.status = 'Approved'
    db.session.commit()
    flash('Overtime request approved.', 'success')
    return redirect(url_for('managerdash_view'))


@app.route("/manager/overtime/<int:req_id>/decline", methods=['POST'])
@token_required(role='Manager')
def decline_overtime(req_id):
    req = OvertimeRequest.query.get_or_404(req_id)
    if req.status != 'Pending':
        flash(f'This request has already been {req.status.lower()}.', 'error')
        return redirect(url_for('managerdash_view'))
    req.status = 'Declined'
    db.session.commit()
    flash('Overtime request declined.', 'success')
    return redirect(url_for('managerdash_view'))


@app.route("/manager/roster/generate", methods=['POST'])
@token_required(role='Manager')
def generate_roster_route():
    try:
        start = parse_date(request.form.get('start_date'))
    except (TypeError, ValueError):
        flash('Please provide a valid window start date.', 'error')
        return redirect(url_for('managerdash_view'))

    end = start + timedelta(days=6)
    batch = generate_roster(start, end)
    return redirect(url_for('roster_review', batch_id=batch.id))


@app.route("/manager/roster/<int:batch_id>")
@token_required(role='Manager')
def roster_review(batch_id):
    batch = RosterBatch.query.get_or_404(batch_id)
    duties = Duty.query.filter_by(batch_id=batch_id).all()
    uncovered = UncoveredSlot.query.filter_by(batch_id=batch_id).all()
    persons = Security.query.order_by(Security.idno).all()
    places = Place.query.order_by(Place.id).all()

    days = [batch.start_date + timedelta(days=i) for i in range((batch.end_date - batch.start_date).days + 1)]
    slot_map = {(d.ddate, d.shift, d.placeid): d for d in duties}
    uncovered_set = {(u.ddate, u.shift, u.placeid) for u in uncovered}

    return render_template(
        'roster_review.html', batch=batch, days=days, places=places,
        persons=persons, slot_map=slot_map, uncovered_set=uncovered_set,
    )


@app.route("/manager/roster/<int:batch_id>/reassign/<int:duty_id>", methods=['POST'])
@token_required(role='Manager')
def reassign_duty(batch_id, duty_id):
    batch = RosterBatch.query.get_or_404(batch_id)
    duty = Duty.query.get_or_404(duty_id)
    if duty.batch_id != batch.id:
        abort(404)
    if batch.status != 'draft':
        flash('Cannot reassign a published roster.', 'error')
        return redirect(url_for('roster_review', batch_id=batch.id))

    new_idno = request.form.get('didno')

    person = Security.query.filter_by(idno=new_idno).first()
    if person is None:
        flash('That is not a valid security person ID.', 'error')
        return redirect(url_for('roster_review', batch_id=batch.id))

    on_leave = Absence.query.filter(
        Absence.idno == new_idno, Absence.status == 'Approved',
        Absence.sdate <= duty.ddate, Absence.edate >= duty.ddate,
    ).first()
    if on_leave is not None:
        flash('That person is on approved leave for this date.', 'error')
        return redirect(url_for('roster_review', batch_id=batch.id))

    conflict = Duty.query.filter(
        Duty.didno == new_idno, Duty.ddate == duty.ddate,
        Duty.shift == duty.shift, Duty.id != duty.id,
    ).first()
    if conflict is not None:
        flash('That person is already assigned elsewhere for this date and shift.', 'error')
        return redirect(url_for('roster_review', batch_id=batch.id))

    duty.didno = new_idno
    db.session.commit()
    flash('Duty reassigned.', 'success')
    return redirect(url_for('roster_review', batch_id=batch.id))


@app.route("/manager/roster/<int:batch_id>/publish", methods=['POST'])
@token_required(role='Manager')
def publish_roster(batch_id):
    batch = RosterBatch.query.get_or_404(batch_id)
    batch.status = 'published'
    db.session.commit()
    return redirect(url_for('roster_review', batch_id=batch.id))


@app.route("/registration", methods=['GET', 'POST'])
def registration():
    if request.method == 'POST':
        name = request.form.get('name')
        username = request.form.get('username')
        domain = request.form.get('domain')
        idno = request.form.get('idno')
        password = request.form.get('pword')
        cpword = request.form.get('cpword')

        if password != cpword:
            flash('Password does not match.', 'error')
            return redirect(url_for('registration'))

        pword = bcrypt.generate_password_hash(password).decode('utf-8')
        if domain == "Manager":
            entry = Manager(name=name, username=username, domain=domain, idno=idno, pword=pword)
        else:
            entry = Security(name=name, username=username, domain=domain, idno=idno, pword=pword)
        db.session.add(entry)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('That username or ID number is already taken.', 'error')
            return redirect(url_for('registration'))

        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('managerLogin' if domain == 'Manager' else 'securityLogin'))

    return render_template('registration.html')


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
