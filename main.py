import os
from datetime import datetime, timedelta
from functools import wraps

import jwt
from dotenv import load_dotenv
from flask_bcrypt import Bcrypt
from flask import Flask, render_template, redirect, url_for, request, g, abort, make_response
from flask_sqlalchemy import SQLAlchemy

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
    idno = db.Column(db.String(120), unique=True, nullable=False)
    sdate = db.Column(db.String, unique=False, nullable=False)
    edate = db.Column(db.String, unique=False, nullable=False)
    reason = db.Column(db.String(120), unique=False, nullable=False)
    status = db.Column(db.String(120), unique=False, nullable=False)
    timestamp = db.Column(db.String(120), unique=False, nullable=False)

class Place(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=False, nullable=False)

class Duty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ddate = db.Column(db.String, unique=False, nullable=False)
    didno = db.Column(db.String(120), unique=True, nullable=False)
    stime = db.Column(db.String, unique=False, nullable=False)
    etime = db.Column(db.String, unique=False, nullable=False)
    placeid = db.Column(db.Integer, db.ForeignKey('place.id'), nullable=False)
    place = db.relationship('Place', backref='duties')


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
        security = Security.query.filter_by(domain='Security').order_by(Security.name).all()
        abes = Absence.query.filter_by(status='Pending').order_by(Absence.timestamp).all()
        duty = Duty.query.order_by(Duty.ddate).all()
        resp = make_response(render_template(
            'managerdash.html', security=security, abes=abes, username=data.username, duty=duty
        ))
        resp.set_cookie('token', token, httponly=True)
        return resp

    return 'Dont Login'


@app.route("/SecurityLogin", methods=['GET', 'POST'])
def securityLogin():
    if request.method == 'GET':
        return render_template('SecurityLogin.html')

    username = request.form.get('username')
    pword = request.form.get('pword')
    data1 = Security.query.filter_by(username=username).first()

    if data1 is not None and bcrypt.check_password_hash(data1.pword, pword):
        token = generate_token(data1.idno, 'Security')
        duty = Duty.query.filter_by(didno=data1.idno).order_by(Duty.ddate).all()
        resp = make_response(render_template('securitydash.html', duty=duty))
        resp.set_cookie('token', token, httponly=True)
        return resp

    return 'Dont Login'


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
        ddate = request.form.get('ddate')
        stime = request.form.get('stime')
        etime = request.form.get('etime')
        placeid = int(request.form.get('placeid'))

        place = Place.query.get(placeid)
        if place is None:
            place = Place(id=placeid, name=f'Place {placeid}')
            db.session.add(place)

        sduty = Duty(didno=didno, ddate=ddate, stime=stime, etime=etime, placeid=placeid)
        db.session.add(sduty)
        db.session.commit()

    return render_template("createduty.html")


@app.route("/securitydashboard", methods=['GET', 'POST'])
@token_required(role='Security')
def securitydashboard():
    if request.method == 'POST':
        sdate = request.form.get('sdate')
        edate = request.form.get('edate')
        reason = request.form.get('reason')
        absence = Absence(
            idno=g.user['idno'], sdate=sdate, edate=edate, reason=reason,
            status='Pending', timestamp=datetime.now()
        )
        db.session.add(absence)
        db.session.commit()

    duty = Duty.query.filter_by(didno=g.user['idno']).order_by(Duty.ddate).all()
    return render_template('securitydash.html', duty=duty)


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
            return "Password does not match"

        pword = bcrypt.generate_password_hash(password).decode('utf-8')
        if domain == "Manager":
            entry = Manager(name=name, username=username, domain=domain, idno=idno, pword=pword)
        else:
            entry = Security(name=name, username=username, domain=domain, idno=idno, pword=pword)
        db.session.add(entry)
        db.session.commit()

    return render_template('registration.html')


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
