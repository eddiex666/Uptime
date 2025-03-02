from flask import Flask, render_template, request, jsonify
import requests
import threading
import time
import socket
import subprocess
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime


# start

app = Flask(__name__)

# Database setup
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///sites.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class MonitoredSite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    check_type = db.Column(db.String(50), nullable=False)  # URL, PING, PORT, SCREEN
    url = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=True)  # Kun for port-sjekk
    status = db.Column(db.String(50), default="Unknown")
    last_checked = db.Column(db.DateTime, default=datetime.utcnow)
    last_status_change = db.Column(db.DateTime, default=datetime.utcnow)

    # Unik kombinasjon av URL + PORT
    __table_args__ = (db.UniqueConstraint('url', 'port', name='unique_url_port'),)


# Funksjoner for sjekkene
def check_url(url):
    try:
        response = requests.get(url, timeout=5)
        return "Up" if response.status_code == 200 else "Down"
    except:
        return "Down"

def check_port(host, port):
    try:
        with socket.create_connection((host, port), timeout=5):
            return "Up"
    except:
        return "Down"

def check_ping(ip):
    try:
        result = subprocess.run(["ping", "-c", "1", ip], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return "Up" if result.returncode == 0 else "Down"
    except:
        return "Down"

def check_screen(session_name):
    try:
        result = subprocess.run(["screen", "-list"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return "Up" if session_name in result.stdout else "Down"
    except:
        return "Down"


def check_sites():
    with app.app_context():  # Ensures Flask's DB context is active
        while True:
            sites = MonitoredSite.query.all()
            for site in sites:
                previous_status = site.status  

                if site.check_type == "URL":
                    site.status = check_url(site.url)
                elif site.check_type == "PORT":
                    if site.port:
                        site.status = check_port(site.url, site.port)
                elif site.check_type == "PING":
                    site.status = check_ping(site.url)
                elif site.check_type == "SCREEN":
                    site.status = check_screen(site.url)

                site.last_checked = datetime.utcnow()

                if site.status != previous_status:
                    site.last_status_change = datetime.utcnow()

                db.session.commit()  # Ensure changes are saved
            time.sleep(30)  # Check every 30 seconds




@app.route("/")
def index():
    return render_template("index.html")


@app.route("/add_site", methods=["POST"])
def add_site():
    name = request.form.get("name")
    url = request.form.get("url")
    check_type = request.form.get("check_type")
    port = request.form.get("port")

    port = int(port) if port and check_type == "PORT" else None

    # Sjekk om samme URL + PORT allerede finnes
    existing_entry = MonitoredSite.query.filter_by(url=url, port=port).first()
    if existing_entry:
        return jsonify(success=False, error="Denne URL + PORT-kombinasjonen eksisterer allerede."), 400

    new_site = MonitoredSite(name=name, url=url, check_type=check_type, port=port, status="Checking...")
    db.session.add(new_site)
    db.session.commit()

    return jsonify(success=True)




@app.route("/edit_site", methods=["POST"])
def edit_site():
    site_id = request.form.get("id")
    name = request.form.get("name")
    url = request.form.get("url")
    check_type = request.form.get("check_type")
    port = request.form.get("port")

    site = MonitoredSite.query.get(site_id)
    if site:
        site.name = name
        site.url = url
        site.check_type = check_type
        site.port = int(port) if check_type == "PORT" and port else None
        db.session.commit()
        return jsonify(success=True)
    return jsonify(success=False, error="Site not found")

@app.route("/get_status")
def get_status():
    sites = MonitoredSite.query.all()
    return jsonify([
        { 
            "id": site.id, 
            "name": site.name, 
            "url": site.url, 
            "check_type": site.check_type, 
            "port": site.port, 
            "status": site.status, 
            "last_checked": site.last_checked.strftime("%Y-%m-%d %H:%M:%S") if site.last_checked else "N/A",
            "last_status_change": site.last_status_change.strftime("%Y-%m-%d %H:%M:%S") if site.last_status_change else "N/A"
        } 
        for site in sites
    ])

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    threading.Thread(target=check_sites, daemon=True).start()  # Runs the checker
    app.run(debug=True, port=8090, host="0.0.0.0")
