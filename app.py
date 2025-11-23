"""
UrbanTaskManager - FIXED BACKEND (CORS + Add Task + Auto Scheduler)
"""

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timezone
import math, os

app = Flask(__name__)
CORS(app)

BASE_DB = "urban_task_static.db"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{BASE_DB}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ----------------- MODELS -----------------
class Resource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String)
    type = db.Column(db.String)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    capacity = db.Column(db.Integer)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String)
    description = db.Column(db.String)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    urgency = db.Column(db.Integer)
    status = db.Column(db.String, default="pending")
    created_at = db.Column(
        db.String,
        default=lambda: datetime.now(timezone.utc).isoformat()
    )

class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer)
    resource_id = db.Column(db.Integer)
    eta_minutes = db.Column(db.Integer)
    assigned_at = db.Column(
        db.String,
        default=lambda: datetime.now(timezone.utc).isoformat()
    )

# ----------------- UTILS -----------------
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ----------------- INITIAL DB -----------------
def init_db(seed=True):
    """Create tables and seed data the first time."""
    with app.app_context():
        first = not os.path.exists(BASE_DB)
        db.create_all()
        if seed and first:
            seed_data()

def seed_data():
    db.session.add_all([
        Resource(name="Team A", type="maintenance", lat=17.435, lon=78.444, capacity=2),
        Resource(name="Team B", type="waste",       lat=17.430, lon=78.450, capacity=1),
        Resource(name="Team C", type="emergency",   lat=17.440, lon=78.430, capacity=1),
    ])
    db.session.commit()

# ✅ IMPORTANT: ensure DB is initialized even under gunicorn on Render
init_db(seed=True)

# ----------------- SCHEDULER -----------------
def current_load(res_id):
    return Assignment.query.filter_by(resource_id=res_id).count()

def greedy_scheduler():
    tasks = Task.query.filter_by(status="pending").all()
    res = Resource.query.all()
    out = []

    for t in sorted(tasks, key=lambda x: -x.urgency):
        best = None
        best_score = -999
        best_dist = None

        for r in res:
            load = current_load(r.id)
            if load >= r.capacity:
                continue

            d = haversine(t.lat, t.lon, r.lat, r.lon)
            score = 0.6*(t.urgency/10) - 0.3*(d/20) - 0.1*(load/r.capacity)

            if score > best_score:
                best_score = score
                best = r
                best_dist = d

        if best:
            eta = int(best_dist/30 * 60) + 5
            a = Assignment(task_id=t.id, resource_id=best.id, eta_minutes=eta)
            t.status = "assigned"
            db.session.add(a)
            db.session.commit()

            out.append({"task": t.title, "resource": best.name, "eta": eta})

    return out

# ----------------- API ROUTES -----------------

@app.route("/")
def home():
    return "UrbanTaskManager backend is running"

@app.route("/api/tasks", methods=["GET"])
def list_tasks():
    tasks = Task.query.all()
    result = []
    for t in tasks:
        assign = Assignment.query.filter_by(task_id=t.id).order_by(Assignment.id.desc()).first()
        res_name = None
        eta = None
        if assign:
            res = Resource.query.get(assign.resource_id)
            res_name = res.name if res else None
            eta = assign.eta_minutes

        result.append({
            "id": t.id,
            "title": t.title,
            "urgency": t.urgency,
            "status": t.status,
            "resource": res_name,
            "eta": eta
        })
    return jsonify(result)

@app.route("/api/resources")
def list_resources():
    r = Resource.query.all()
    return jsonify([
        {
            "id": x.id,
            "name": x.name,
            "capacity": x.capacity,
            "current_load": current_load(x.id)
        }
        for x in r
    ])

@app.route("/api/tasks", methods=["POST"])
@app.route("/api/add_task", methods=["POST"])
def add_task():
    d = request.get_json()
    task = Task(
        title=d["title"],
        description=d.get("description", ""),
        lat=float(d["lat"]),
        lon=float(d["lon"]),
        urgency=int(d["urgency"])
    )
    db.session.add(task)
    db.session.commit()

    greedy_scheduler()

    return jsonify({"msg": "Task Added & Scheduled", "id": task.id})

@app.route("/api/schedule", methods=["POST"])
def run_scheduler():
    out = greedy_scheduler()
    return jsonify({"assigned": out, "count": len(out)})

# ----------------- RUN (local only) -----------------
if __name__ == "__main__":
    # For local testing; on Render gunicorn will ignore this block
    print("Backend running on http://127.0.0.1:5000")
    app.run(debug=True)
