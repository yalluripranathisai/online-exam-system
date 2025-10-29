from pymongo import MongoClient
from werkzeug.security import generate_password_hash

client = MongoClient('mongodb://localhost:27017/')
db = client['online_exam_db']
users = db['users']

# Clear and re-create sample users (safe for local dev only)
users.delete_many({})
users.insert_many([
    {'username': 'faculty1', 'password_hash': generate_password_hash('password123'), 'role': 'faculty'},
    {'username': 'student1', 'password_hash': generate_password_hash('password123'), 'role': 'student'}
])

tests = db['tests']
questions = db['questions']
submissions = db['submissions']
tests.delete_many({})
questions.delete_many({})
submissions.delete_many({})

faculty = users.find_one({'username': 'faculty1'})
res = tests.insert_one({'title': 'Sample Quiz', 'type': 'quiz', 'assigned_to': 'all', 'created_by': faculty['_id']})
test_id = res.inserted_id
questions.insert_many([
    {'test_id': test_id, 'qtext': 'What is 2+2?', 'type': 'numeric', 'marks': 1, 'expected': '4'},
    {'test_id': test_id, 'qtext': 'Select prime numbers', 'type': 'mcq_multi', 'marks': 2,
     'options': ['2', '3', '4', '6'], 'corrects': ['2', '3']},
    {'test_id': test_id, 'qtext': 'Capital of France?', 'type': 'short_text', 'marks': 1, 'expected': 'paris'},
    {'test_id': test_id, 'qtext': 'Choose the color red', 'type': 'mcq_single', 'marks': 1,
     'options': ['red', 'blue', 'green'], 'corrects': ['red']}
])
print("Sample data inserted")
