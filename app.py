from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import datetime
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import os

# Build version 2025-11-05 - Force fresh deploy

# ---------------------------------------------------------
# Flask and Mongo setup
# ---------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET', 'devsecret')

port = int(os.environ.get("PORT", 8080))
MONGO_URI = os.environ.get("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client["online_exam"]

# Collections
users_col = db['users']
tests_col = db['tests']
questions_col = db['questions']
submissions_col = db['submissions']


# ---------------------------------------------------------
# Helper functions
# ---------------------------------------------------------
def current_user():
    uid = session.get('user_id')
    if not uid:
        return None
    try:
        return users_col.find_one({'_id': ObjectId(uid)})
    except Exception:
        return None


def serialize_doc_for_template(doc):
    if doc is None:
        return None
    d = dict(doc)
    if '_id' in d:
        d['id'] = str(d['_id'])
    if 'test_id' in d and isinstance(d['test_id'], ObjectId):
        d['test_id_str'] = str(d['test_id'])
    if 'student_id' in d and isinstance(d['student_id'], ObjectId):
        d['student_id_str'] = str(d['student_id'])
    return d


# ---------------------------------------------------------
# Routes: Authentication
# ---------------------------------------------------------
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
    return render_template('register.html')


# ---------------------------------------------------------
# Faculty Routes
# ---------------------------------------------------------
@app.route('/faculty')
def faculty_dashboard():
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))

    tests_db = list(tests_col.find({'created_by': user['_id']}).sort('created_at', -1))
    tests = [serialize_doc_for_template(t) for t in tests_db]

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

        if duration.isdigit():
            test_doc['duration_minutes'] = int(duration)
        if time_per_q.isdigit():
            test_doc['time_per_question'] = int(time_per_q)

        res = tests_col.insert_one(test_doc)
        flash('Test created. Now add questions.', 'success')
        return redirect(url_for('add_question', test_id=str(res.inserted_id)))

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
            options = [o.strip() for o in request.form.getlist('option') if o.strip()]
            corrects = [c for c in request.form.getlist('correct') if c.strip()]
            question = {'test_id': test_db['_id'], 'qtext': qtext, 'type': qtype,
                        'marks': marks, 'options': options, 'corrects': corrects}
        else:
            expected = request.form.get('expected', '').strip()
            question = {'test_id': test_db['_id'], 'qtext': qtext, 'type': qtype,
                        'marks': marks, 'expected': expected}

        questions_col.insert_one(question)
        flash('Question added', 'success')
        return redirect(url_for('add_question', test_id=test_id))

    qs_db = list(questions_col.find({'test_id': test_db['_id']}))
    qs = [serialize_doc_for_template(q) for q in qs_db]
    return render_template('add_question.html', test=serialize_doc_for_template(test_db), questions=qs)


@app.route('/faculty/delete_test/<test_id>', methods=['POST'])
def delete_test(test_id):
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))

    tests_col.delete_one({'_id': ObjectId(test_id)})
    submissions_col.delete_many({'test_id': ObjectId(test_id)})
    flash('Test deleted successfully', 'success')
    return redirect(url_for('faculty_dashboard'))


@app.route('/faculty/test_scores/<test_id>')
def test_scores(test_id):
    user = current_user()
    if not user or user.get('role') != 'faculty':
        return redirect(url_for('login'))

    test = tests_col.find_one({'_id': ObjectId(test_id)})
    if not test:
        flash('Test not found', 'danger')
        return redirect(url_for('faculty_dashboard'))

    submissions = list(submissions_col.find({'test_id': ObjectId(test_id)}))
    scores = []
    for s in submissions:
        student = users_col.find_one({'_id': s['student_id']})
        scores.append({
            'student': student['username'] if student else 'Unknown',
            'score': s['score'],
            'possible': s['possible'],
            'submitted_at': s.get('submitted_at')
        })

    return render_template('faculty_scores.html', test=serialize_doc_for_template(test), 
                         scores=scores, user=serialize_doc_for_template(user))


# ---------------------------------------------------------
# Student Routes
# ---------------------------------------------------------
@app.route('/student')
def student_dashboard():
    user = current_user()
    if not user or user.get('role') != 'student':
        return redirect(url_for('login'))

    tests_db = list(tests_col.find({'$or': [{'assigned_to': 'all'}, {'assigned_to': user.get('username')}]}).sort('created_at', -1))
    summaries, total_scored, total_possible = [], 0.0, 0.0

    for t in tests_db:
        qs_db = list(questions_col.find({'test_id': t['_id']}))
        possible = sum(float(q.get('marks', 0)) for q in qs_db)
        submission = submissions_col.find_one({'test_id': t['_id'], 'student_id': user['_id']})
        scored = float(submission.get('score')) if submission else None
        if scored is not None:
            total_scored += scored
            total_possible += possible
        summaries.append({'test': serialize_doc_for_template(t), 'possible': possible, 'scored': scored})

    avg = (total_scored / total_possible * 100) if total_possible > 0 else None
    return render_template('student_dashboard.html', user=serialize_doc_for_template(user),
                           summaries=summaries, avg=avg, total_scored=total_scored, total_possible=total_possible)


@app.route('/student/take_test/<test_id>', methods=['GET', 'POST'])
def take_test(test_id):
    user = current_user()
    if not user or user.get('role') != 'student':
        return redirect(url_for('login'))

    try:
        test = tests_col.find_one({'_id': ObjectId(test_id)})
    except Exception:
        test = None

    if not test:
        flash('Test not found', 'danger')
        return redirect(url_for('student_dashboard'))

    # Check if already submitted
    existing_submission = submissions_col.find_one({'test_id': test['_id'], 'student_id': user['_id']})
    if existing_submission:
        flash('You have already submitted this test', 'info')
        return redirect(url_for('student_dashboard'))

    questions = list(questions_col.find({'test_id': test['_id']}))
    
    if request.method == 'POST':
        score = 0.0
        total_possible = 0.0

        for q in questions:
            qid = str(q['_id'])
            total_possible += float(q.get('marks', 0))

            if q['type'] == 'mcq_single':
                answer = request.form.get(f'answer_{qid}', '').strip()
                if answer in q.get('corrects', []):
                    score += float(q.get('marks', 0))

            elif q['type'] == 'mcq_multiple':
                answers = request.form.getlist(f'answer_{qid}')
                corrects = set(q.get('corrects', []))
                if set(answers) == corrects:
                    score += float(q.get('marks', 0))

            elif q['type'] == 'short_text':
                answer = request.form.get(f'answer_{qid}', '').strip().lower()
                expected = q.get('expected', '').strip().lower()
                if answer == expected:
                    score += float(q.get('marks', 0))

            elif q['type'] == 'long_text':
                # For long text, mark as needs manual grading (give partial credit or 0)
                # You can implement manual grading later
                pass

        # Save submission
        submissions_col.insert_one({
            'test_id': test['_id'],
            'student_id': user['_id'],
            'score': score,
            'possible': total_possible,
            'submitted_at': datetime.utcnow()
        })

        flash(f'Test submitted! Score: {score}/{total_possible}', 'success')
        return redirect(url_for('student_dashboard'))

    return render_template('take_test.html', test=serialize_doc_for_template(test),
                         questions=[serialize_doc_for_template(q) for q in questions])


# ---------------------------------------------------------
# PDF Download (Student Report)
# ---------------------------------------------------------
@app.route('/student/download_report/<username>')
def download_student_report(username):
    user = current_user()
    if not user or user.get('username') != username:
        flash("Unauthorized access", "danger")
        return redirect(url_for('student_dashboard'))

    student_doc = users_col.find_one({"username": username})
    if not student_doc:
        flash("Student not found", "danger")
        return redirect(url_for('student_dashboard'))

    submissions = list(submissions_col.find({"student_id": student_doc['_id']}))
    tests = {t['_id']: t for t in tests_col.find()}

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
                pdf.drawString(50, y, f"Test: {test.get('title', 'Untitled')} | Score: {sub.get('score', 0)}/{sub.get('possible', 0)}")
                y -= 20
                if y < 50:
                    pdf.showPage()
                    y = 800

    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{username}_report.pdf", mimetype='application/pdf')


# ---------------------------------------------------------
# Main entry
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port, debug=False)