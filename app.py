from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
import os
import csv

port = int(os.environ.get("PORT", 8080))

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'devsecret')

# MongoDB connection (edit if using Atlas)
MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["sample_mflix"]






# Collections
users_col = db['users']
tests_col = db['tests']
questions_col = db['questions']
submissions_col = db['submissions']


# -------------------------
# Helpers
# -------------------------
def current_user():
    """Return the current user document or None."""
    uid = session.get('user_id')
    if not uid:
        return None
    try:
        return users_col.find_one({'_id': ObjectId(uid)})
    except Exception:
        return None


def serialize_doc_for_template(doc):
    """Return a shallow copy of doc with additional human-friendly id fields for templates."""
    if doc is None:
        return None
    d = dict(doc)  # shallow copy
    if '_id' in d:
        d['id'] = str(d['_id'])
    # friendly conversions (if present)
    if 'test_id' in d and isinstance(d['test_id'], ObjectId):
        d['test_id_str'] = str(d['test_id'])
    if 'student_id' in d and isinstance(d['student_id'], ObjectId):
        d['student_id_str'] = str(d['student_id'])
    return d


# -------------------------
# Routes: Authentication
# -------------------------
@app.route('/')
def index():
    if session.get('user_id'):
        user = current_user()
        if user and user.get('role') == 'faculty':
            return redirect(url_for('faculty_dashboard'))
        return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = users_col.find_one({'username': username})
        if user and check_password_hash(user.get('password_hash', ''), password):
            session['user_id'] = str(user['_id'])
            session['role'] = user.get('role')
            session['username'] = user.get('username')
            flash('Logged in successfully', 'success')
            if user.get('role') == 'faculty':
                return redirect(url_for('faculty_dashboard'))
            return redirect(url_for('student_dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'info')
    return redirect(url_for('login'))


# -------------------------
# Routes: Faculty
# -------------------------
@app.route('/faculty')
def faculty_dashboard():
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))

    # fetch tests created by this faculty
    tests_db = list(tests_col.find({'created_by': user['_id']}).sort('created_at', -1))

    # prepare tests with string id for templates
    tests = []
    for t in tests_db:
        t_copy = dict(t)
        t_copy['id'] = str(t_copy.get('_id'))
        tests.append(t_copy)

    return render_template('faculty_dashboard.html', user=serialize_doc_for_template(user), tests=tests)



@app.route('/faculty/create_test', methods=['GET', 'POST'])
def create_test():
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        test_type = request.form.get('test_type', 'assignment')
        assigned_to = request.form.get('assigned_to', 'all').strip()

        # New time fields
        duration = request.form.get('duration_minutes', '').strip()
        time_per_q = request.form.get('time_per_question', '').strip()

        if not title:
            flash('Title required', 'danger')
            return redirect(url_for('create_test'))

        test_doc = {
            'title': title,
            'type': test_type,
            'assigned_to': assigned_to,
            'created_by': user['_id'],
            'created_at': datetime.utcnow()
        }

        # Add time fields only if provided
        if duration.isdigit():
            test_doc['duration_minutes'] = int(duration)
        if time_per_q.isdigit():
            test_doc['time_per_question'] = int(time_per_q)

        res = tests_col.insert_one(test_doc)
        flash('Test created. Now add questions.', 'success')
        return redirect(url_for('add_question', test_id=str(res.inserted_id)))

    # pass list of student usernames (optional)
    students_db = list(users_col.find({'role': 'student'}, {'username': 1}))
    students = [s.get('username') for s in students_db]
    return render_template('create_test.html', students=students)

@app.route('/faculty/<test_id>/add_question', methods=['GET', 'POST'])
def add_question(test_id):
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))
    try:
        test_db = tests_col.find_one({'_id': ObjectId(test_id)})
    except Exception:
        test_db = None
    if not test_db:
        flash('Test not found', 'danger')
        return redirect(url_for('faculty_dashboard'))
    if request.method == 'POST':
        qtext = request.form.get('qtext', '').strip()
        qtype = request.form.get('qtype', 'short_text')
        marks_raw = request.form.get('marks', '1').strip()
        try:
            marks = float(marks_raw)
        except Exception:
            marks = 1.0
        if qtype.startswith('mcq'):
            # collect options and corrects (checkbox values contain option text)
            options = [o.strip() for o in request.form.getlist('option') if o.strip()]
            # 'correct' checkboxes will have value equal to option text (set in template JS)
            corrects = [c for c in request.form.getlist('correct') if c.strip()]
            question = {
                'test_id': test_db['_id'],
                'qtext': qtext,
                'type': qtype,
                'marks': marks,
                'options': options,
                'corrects': corrects
            }
        else:
            expected = request.form.get('expected', '').strip()
            question = {
                'test_id': test_db['_id'],
                'qtext': qtext,
                'type': qtype,
                'marks': marks,
                'expected': expected
            }
        questions_col.insert_one(question)
        flash('Question added', 'success')
        return redirect(url_for('add_question', test_id=test_id))

    qs_db = list(questions_col.find({'test_id': test_db['_id']}))
    qs = [serialize_doc_for_template(q) for q in qs_db]
    return render_template('add_question.html', test=serialize_doc_for_template(test_db), questions=qs)


@app.route('/faculty/<test_id>/submissions')
def view_submissions(test_id):
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))
    try:
        test_db = tests_col.find_one({'_id': ObjectId(test_id)})
    except Exception:
        test_db = None
    if not test_db:
        flash('Test not found', 'danger')
        return redirect(url_for('faculty_dashboard'))
    subs_db = list(submissions_col.find({'test_id': test_db['_id']}))
    subs = []
    for s in subs_db:
        s_copy = dict(s)
        s_copy['id'] = str(s_copy.get('_id'))
        s_copy['test_id_str'] = str(s_copy.get('test_id'))
        # student username
        stu = users_col.find_one({'_id': s_copy.get('student_id')})
        s_copy['student_username'] = stu.get('username') if stu else 'Unknown'
        subs.append(s_copy)
    return render_template('view_submissions.html', test=serialize_doc_for_template(test_db), submissions=subs)
from bson.objectid import ObjectId

# ----- DELETE TEST -----
@app.route('/faculty/delete_test/<test_id>', methods=['POST'])
def delete_test(test_id):
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))

    tests_col.delete_one({'_id': ObjectId(test_id)})
    submissions_col.delete_many({'test_id': ObjectId(test_id)})  # also remove related submissions
    return redirect(url_for('faculty_dashboard'))


# ----- VIEW STUDENT SCORES -----
@app.route('/faculty/test_scores/<test_id>')
def test_scores(test_id):
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))

    test = tests_col.find_one({'_id': ObjectId(test_id)})
    if not test:
        return "Test not found", 404

    # Fetch all submissions for this test
    submissions = list(submissions_col.find({'test_id': ObjectId(test_id)}))

    # Attach student details
    scores = []
    for s in submissions:
        student = users_col.find_one({'_id': s['student_id']})
        scores.append({
            'student': student['username'] if student else 'Unknown',
            'score': s['score'],
            'possible': s['possible'],
            'submitted_at': s.get('submitted_at')
        })

    return render_template('faculty_scores.html', test=test, scores=scores, user=user)



# -------------------------
# Routes: Student
# -------------------------
@app.route('/student')
def student_dashboard():
    user = current_user()
    if not user or user.get('role') != 'student':
        return redirect(url_for('login'))
    tests_db = list(tests_col.find({'$or': [{'assigned_to': 'all'}, {'assigned_to': user.get('username')}]})
                    .sort('created_at', -1))
    summaries = []
    total_scored = 0.0
    total_possible = 0.0

    for t in tests_db:
        qs_db = list(questions_col.find({'test_id': t['_id']}))
        possible = sum(float(q.get('marks', 0)) for q in qs_db)
        submission = submissions_col.find_one({'test_id': t['_id'], 'student_id': user['_id']})
        scored = float(submission.get('score')) if submission else None
        if scored is not None:
            total_scored += scored
            total_possible += possible
        t_display = serialize_doc_for_template(t)
        summaries.append({'test': t_display, 'possible': possible, 'scored': scored})

    avg = (total_scored / total_possible * 100) if total_possible > 0 else None
    return render_template('student_dashboard.html', user=serialize_doc_for_template(user),
                           summaries=summaries, avg=avg, total_scored=total_scored, total_possible=total_possible)


@app.route('/student/take/<test_id>', methods=['GET'])
def take_test(test_id):
    user = current_user()
    if not user or user.get('role') != 'student':
        return redirect(url_for('login'))
    try:
        test_db = tests_col.find_one({'_id': ObjectId(test_id)})
    except Exception:
        test_db = None
    if not test_db:
        flash('Test not found', 'danger')
        return redirect(url_for('student_dashboard'))
    qs_db = list(questions_col.find({'test_id': test_db['_id']}))
    # prepare questions for template: make q['id'] strings
    qs = []
    for q in qs_db:
        qd = dict(q)
        qd['id'] = str(qd.get('_id'))
        qs.append(qd)
    return render_template('take_test.html', test=serialize_doc_for_template(test_db), questions=qs)


@app.route('/student/submit/<test_id>', methods=['POST'])
def submit_test(test_id):
    user = current_user()
    if not user or user.get('role') != 'student':
        return redirect(url_for('login'))
    try:
        test_db = tests_col.find_one({'_id': ObjectId(test_id)})
    except Exception:
        test_db = None
    if not test_db:
        flash('Test not found', 'danger')
        return redirect(url_for('student_dashboard'))

    qs_db = list(questions_col.find({'test_id': test_db['_id']}))
    total_score = 0.0
    total_possible = 0.0
    answers = {}

    for q in qs_db:
        qid = str(q['_id'])
        marks = float(q.get('marks', 0))
        total_possible += marks
        given = request.form.getlist(qid)
        # store whatever was given (strings)
        answers[qid] = given
        qtype = q.get('type')
        if qtype == 'mcq_single':
            corrects = q.get('corrects', [])
            if len(given) == 1 and given[0] in corrects:
                total_score += marks
        elif qtype == 'mcq_multi':
            corrects = set(q.get('corrects', []))
            given_set = set(given)
            # full credit only if sets match exactly
            if given_set == corrects:
                total_score += marks
        elif qtype == 'short_text':
            expected = str(q.get('expected', '')).strip().lower()
            if given and given[0].strip().lower() == expected:
                total_score += marks
        elif qtype == 'numeric':
            expected = str(q.get('expected', '')).strip()
            if given and given[0].strip() == expected:
                total_score += marks
        else:
            # unsupported types -> 0
            pass

    submission_doc = {
        'test_id': test_db['_id'],
        'student_id': user['_id'],
        'answers': answers,
        'score': total_score,
        'possible': total_possible,
        'submitted_at': datetime.utcnow()
    }

    submissions_col.update_one(
        {'test_id': test_db['_id'], 'student_id': user['_id']},
        {'$set': submission_doc},
        upsert=True
    )

    flash(f'Submitted. You scored {total_score} / {total_possible}', 'success')
    return redirect(url_for('student_dashboard'))


# -------------------------
# Performance route (student)
# -------------------------
@app.route('/student/performance')
def student_performance():
    user = current_user()
    if not user or user.get('role') != 'student':
        return redirect(url_for('login'))

    subs_db = list(submissions_col.find({'student_id': user['_id']}).sort('submitted_at', -1))
    subs = []
    total_scored = 0.0
    total_possible = 0.0
    for s in subs_db:
        s_copy = dict(s)
        s_copy['id'] = str(s_copy.get('_id'))
        s_copy['test_id_str'] = str(s_copy.get('test_id'))
        # fetch test title
        test_doc = tests_col.find_one({'_id': s_copy.get('test_id')})
        s_copy['test_title'] = test_doc.get('title') if test_doc else 'Unknown'
        s_copy['score'] = float(s_copy.get('score', 0))
        s_copy['possible'] = float(s_copy.get('possible', 0))
        total_scored += s_copy['score']
        total_possible += s_copy['possible']
        subs.append(s_copy)

    percentage = round((total_scored / total_possible) * 100, 2) if total_possible > 0 else None
    perf = {
        'total_scored': total_scored,
        'total_possible': total_possible,
        'percentage': percentage
    }
    labels = [sub.get('test_title', 'Untitled') for sub in subs]
    scores = [sub.get('score', 0) for sub in subs]

    return render_template('student_performance.html',
                       submissions=subs,
                       performance=perf,
                       user=serialize_doc_for_template(user),
                       labels=labels,
                       scores=scores)



# -------------------------
# Registration (demo only)
# -------------------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'student')
        if not username or not password:
            flash('Username and password required', 'danger')
            return redirect(url_for('register'))
        if users_col.find_one({'username': username}):
            flash('Username exists', 'danger')
            return redirect(url_for('register'))
        users_col.insert_one({
            'username': username,
            'password_hash': generate_password_hash(password),
            'role': role,
            'created_at': datetime.utcnow()
        })
        flash('User registered', 'success')
        return redirect(url_for('login'))
    return render_template('login.html')


from flask import send_file
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from bson import ObjectId

@app.route('/student/download_report/<username>')
def download_student_report(username):
    user = current_user()
    if not user or user.get('username') != username:
        flash("Unauthorized access", "danger")
        return redirect(url_for('student_dashboard'))

    # Step 1: Get student ObjectId
    student_doc = users_col.find_one({ "username": username })
    if not student_doc:
        flash("Student not found", "danger")
        return redirect(url_for('student_dashboard'))

    student_id = student_doc['_id']

    # Step 2: Query submissions using student_id
    submissions = list(submissions_col.find({ "student_id": student_id }))
    tests = {t['_id']: t for t in tests_col.find()}

    # Step 3: Generate PDF
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"{username}_report")

    pdf.drawString(50, 800, f"Performance Report — {username}")
    y = 770

    if not submissions:
        pdf.drawString(50, y, "No submissions found.")
    else:
        for sub in submissions:
            test = tests.get(sub['test_id'])
            if test:
                title = test.get('title', 'Untitled')
                test_type = test.get('type', 'Unknown')
                score = sub.get('score', 'N/A')
                possible = sub.get('possible', 'N/A')
                pdf.drawString(50, y, f"Test: {title} | Type: {test_type} | Score: {score}/{possible}")
                y -= 20
                if y < 50:
                    pdf.showPage()
                    y = 800

    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{username}_report.pdf", mimetype='application/pdf')
@app.route('/')
def home():
    return "Online Examination System Running Successfully!"


if __name__ == '__main__':
    # Render provides the port via environment variable
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)