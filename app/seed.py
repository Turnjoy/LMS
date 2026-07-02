from app.models import GlobalSubjectRepository, db


NIGERIAN_NATIONAL_SUBJECTS = [
    ('English Language', 'General'),
    ('General Mathematics', 'General'),
    ('Civic Education', 'General'),
    ('Physics', 'Science'),
    ('Chemistry', 'Science'),
    ('Biology', 'Science'),
    ('Agricultural Science', 'Science'),
    ('Further Mathematics', 'Science'),
    ('Computer Studies', 'Science'),
    ('Geography', 'Science'),
    ('Literature-in-English', 'Arts'),
    ('Government', 'Arts'),
    ('Nigerian History', 'Arts'),
    ('Christian Religious Studies (CRS)', 'Arts'),
    ('Islamic Religious Studies (IRS)', 'Arts'),
    ('French', 'Arts'),
    ('Yoruba', 'Arts'),
    ('Igbo', 'Arts'),
    ('Hausa', 'Arts'),
    ('Visual Art', 'Arts'),
    ('Economics', 'Commercial'),
    ('Commerce', 'Commercial'),
    ('Financial Accounting', 'Commercial'),
    ('Marketing', 'Commercial'),
    ('Insurance', 'Commercial'),
]


def seed_global_subject_repository():
    """Seed standard Nigerian ministry/exam subjects once."""
    created_count = 0

    for name, category in NIGERIAN_NATIONAL_SUBJECTS:
        existing = GlobalSubjectRepository.query.filter_by(name=name).first()
        if existing:
            if existing.category != category:
                existing.category = category
            continue

        db.session.add(GlobalSubjectRepository(name=name, category=category))
        created_count += 1

    db.session.commit()
    return created_count
