"""
Dev-only seed script for local/demo databases. Not for production use.

Run with: python seed.py

Safe to re-run: uses check-then-insert, keyed on Place.name and
Manager/Security.idno. Existing rows are left untouched, nothing is
cleared or overwritten.
"""
from main import app, db, bcrypt, Manager, Security, Place

DUMMY_PASSWORD = 'Password123!'  # dummy/dev-only password shared by every seeded account

PLACE_NAMES = [
    'North1', 'North2', 'South1', 'South2',
    'East1', 'East2', 'West1', 'West2',
]

# 48 is the hard minimum to cover 8 places x 3 shifts with zero slack for leave.
# 55 leaves enough buffer to actually exercise leave/overtime scenarios without
# every request immediately causing an uncovered slot.
SECURITY_COUNT = 55

MANAGER_IDNO = 'M0001'


def seed_places():
    created = 0
    for name in PLACE_NAMES:
        if Place.query.filter_by(name=name).first() is None:
            db.session.add(Place(name=name))
            created += 1
    db.session.commit()
    return created


def seed_manager():
    if Manager.query.filter_by(idno=MANAGER_IDNO).first() is not None:
        return False
    pword = bcrypt.generate_password_hash(DUMMY_PASSWORD).decode('utf-8')
    db.session.add(Manager(
        name='Demo Manager', username='manager1', domain='Manager',
        idno=MANAGER_IDNO, pword=pword,
    ))
    db.session.commit()
    return True


def seed_security():
    created = 0
    for i in range(1, SECURITY_COUNT + 1):
        idno = f'S{i:04d}'
        if Security.query.filter_by(idno=idno).first() is not None:
            continue
        pword = bcrypt.generate_password_hash(DUMMY_PASSWORD).decode('utf-8')
        db.session.add(Security(
            name=f'Guard {i:03d}', username=f'guard{i:03d}',
            domain='Security', idno=idno, pword=pword,
        ))
        created += 1
    db.session.commit()
    return created


def run():
    with app.app_context():
        db.create_all()
        places_created = seed_places()
        manager_created = seed_manager()
        security_created = seed_security()

    print(f'Places created: {places_created} (of {len(PLACE_NAMES)} target)')
    print(f'Manager created: {manager_created} (idno {MANAGER_IDNO}, username manager1)')
    print(f'Security accounts created: {security_created} (of {SECURITY_COUNT} target)')
    print(f'All seeded accounts share the dummy password: {DUMMY_PASSWORD}')


if __name__ == '__main__':
    run()
