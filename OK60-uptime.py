from flask import Flask, render_template, request, jsonify
import requests
import threading
import time
import socket
import os
import subprocess
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///sites.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

AUTH_KEY = "supersecurekey123"

class Agent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    ip_address = db.Column(db.String(255), nullable=False, unique=False)  # Allow multiple IPs with different ports
    port = db.Column(db.Integer, nullable=False, default=8092)  # Default port


class MonitoredSite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=True)
    check_type = db.Column(db.String(50), nullable=False)  
    url = db.Column(db.String(255), nullable=False)
    port = db.Column(db.Integer, nullable=True)  
    status = db.Column(db.String(50), default="Checking...")
    last_checked = db.Column(db.DateTime, default=datetime.utcnow)
    last_status_change = db.Column(db.DateTime, default=datetime.utcnow)

    agent = db.relationship('Agent', backref=db.backref('checks', lazy=True))

def request_agent_check(agent_ip, check_type, url, port):
    try:
        response = requests.post(f"http://{agent_ip}:8092/check", json={
            "auth_key": AUTH_KEY,
            "check_type": check_type,
            "url": url,
            "port": port
        }, timeout=5)
        return response.json().get("status", "ERROR")
    except:
        return "ERROR"

def check_url(url):
    """ Check if a URL is reachable """
    try:
        response = requests.get(url, timeout=5)
        return "OK" if response.status_code == 200 else "ERROR"
    except requests.RequestException:
        return "ERROR"

def check_ping(ip):
    """ Ping an IP address """
    response = os.system(f"ping -c 1 {ip} > /dev/null 2>&1")
    return "OK" if response == 0 else "ERROR"

def check_port(ip, port):
    """ Check if a port is open """
    try:
        with socket.create_connection((ip, port), timeout=5):
            return "OK"
    except:
        return "ERROR"

def check_screen(service_name):
    """ Check if a process is running via screen (Linux) """
    response = os.system(f"screen -ls | grep {service_name} > /dev/null 2>&1")
    return "OK" if response == 0 else "ERROR"

def check_sites():
    with app.app_context():
        while True:
            sites = MonitoredSite.query.all()
            for site in sites:
                previous_status = site.status  

                if site.agent:
                    site.status = request_agent_check(site.agent.ip_address, site.check_type, site.url, site.port)
                else:
                    if site.check_type == "URL":
                        site.status = check_url(site.url)
                    elif site.check_type == "PING":
                        site.status = check_ping(site.url)
                    elif site.check_type == "PORT" and site.port:
                        site.status = check_port(site.url, site.port)
                    elif site.check_type == "SCREEN":
                        site.status = check_screen(site.url)

                site.last_checked = datetime.utcnow()
                if site.status != previous_status:
                    site.last_status_change = datetime.utcnow()
                
                db.session.commit()
            time.sleep(30)

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/add_agent", methods=["POST"])
def add_agent():
    data = request.get_json()
    name = data.get("name")
    ip_address = data.get("ip_address")
    port = data.get("port")

    if not port:
        port = 8092  # Default port

    # Ensure the port is stored as an integer
    try:
        port = int(port)
    except ValueError:
        return jsonify(success=False, error="Invalid port number"), 400

    if Agent.query.filter_by(ip_address=ip_address, port=port).first():
        return jsonify(success=False, error="Agent with this IP and Port already exists"), 400

    new_agent = Agent(name=name, ip_address=ip_address, port=port)
    db.session.add(new_agent)
    db.session.commit()
    return jsonify(success=True)


@app.route("/get_agents")
def get_agents():
    agents = Agent.query.all()
    return jsonify([
        {"id": agent.id, "name": agent.name, "ip_address": agent.ip_address, "port": agent.port}
        for agent in agents
    ])


@app.route("/add_site", methods=["POST"])
def add_site():
    data = request.get_json()
    name = data.get("name")
    url = data.get("url")
    check_type = data.get("check_type")
    port = data.get("port")
    agent_id = data.get("agent_id")

    port = int(port) if port and check_type == "PORT" else None
    agent = Agent.query.get(agent_id) if agent_id else None

    new_site = MonitoredSite(name=name, url=url, check_type=check_type, port=port, agent=agent, status="Checking...")
    db.session.add(new_site)
    db.session.commit()

    return jsonify(success=True)



@app.route("/delete_site", methods=["POST"])
def delete_site():
    data = request.get_json()
    site_id = data.get("id")

    site = MonitoredSite.query.get(site_id)
    if site:
        db.session.delete(site)
        db.session.commit()
        return jsonify(success=True)
    else:
        return jsonify(success=False, error="Site not found"), 404




@app.route("/get_status")
def get_status():
    sites = MonitoredSite.query.all()
    return jsonify([
        { 
            "id": site.id, 
            "name": site.name, 
            "agent": site.agent.name if site.agent else "Local",
            "check_type": site.check_type, 
            "url": site.url, 
            "port": site.port, 
            "status": site.status, 
            "last_checked": site.last_checked.strftime("%Y-%m-%d %H:%M:%S"),
            "last_status_change": site.last_status_change.strftime("%Y-%m-%d %H:%M:%S")
        } 
        for site in sites
    ])

threading.Thread(target=check_sites, daemon=True).start()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=8090, host="0.0.0.0")
